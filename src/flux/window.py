from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

from flux import __version__
from flux.converter import (
    BaseConverter,
    ConverterRegistry,
    ConversionResult,
    UnsupportedFormatError,
    normalize_format,
)
from flux.services import PillowImageConverter, UpdateError, UpdateInfo, Updater


@dataclass
class _Job:
    job_id: str
    thread: threading.Thread
    converter: BaseConverter
    cancel_event: threading.Event
    status: str = "pending"
    progress: int = 0
    output_paths: list[str] = field(default_factory=list)
    error: str | None = None


def _dialog_paths(value: Any) -> list[str]:
    """Normalize a create_file_dialog selection to a list of usable paths.

    The selection type depends on the dialog and the backend: the WinForms
    implementation returns a bare string for a single-select OPEN dialog but a
    tuple for a multi-select one, and the FOLDER dialog is a re-purposed
    OpenFileDialog whose FileNames list is re-wrapped in a tuple
    (webview/platforms/winforms.py: OpenFolderDialog.show -> tuple(FileNames)).
    str() on that tuple produces repr text - "('C:\\\\dir',)", with every
    separator doubled - which no filesystem call accepts, so a selection must
    be unwrapped rather than stringified.
    """
    if isinstance(value, str):
        return [value] if value.strip() else []

    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, str) and item.strip()]

    return []


def _first_path(value: Any) -> str | None:
    """The usable path from a dialog selection, or None when nothing was picked."""
    paths = _dialog_paths(value)
    return paths[0] if paths else None


class FluxAPI:
    def __init__(
        self,
        registry: ConverterRegistry | None = None,
        window: Any | None = None,
    ) -> None:
        self.registry = registry or self._default_registry()
        self._window = window
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()

        # In-app update state (see the checkForUpdate/downloadUpdate/
        # installUpdate methods below). _download_lock is held for the whole
        # download so a double-clicked "Download update" starts one stream,
        # and _downloaded_setup remembers the installer path to hand to
        # installUpdate.
        self._updater = Updater(current_version=__version__)
        self._update_info: UpdateInfo | None = None
        self._downloaded_setup: Path | None = None
        self._download_lock = threading.Lock()
        self._update_last_emit = 0.0

    @staticmethod
    def _default_registry() -> ConverterRegistry:
        registry = ConverterRegistry()
        registry.register(PillowImageConverter())
        return registry

    def attach_window(self, window: Any) -> None:
        self._window = window
        # Registration must not run on the caller's thread: attach_window is
        # invoked before webview.start(), and evaluate_js blocks until the
        # page is ready - that would deadlock the GUI loop before it starts.
        threading.Thread(
            target=self.attach_drop_listener, args=(window,), daemon=True
        ).start()

    def attach_drop_listener(self, window: Any) -> None:
        """Register the Python-side drop listener that enables path delivery.

        WebView2 only forwards dropped files to the host (as CoreWebView2File
        AdditionalObjects) while pywebview has at least one Python-side DOM
        drop listener (webview/dom/element.py: Element.on('drop', ...)
        increments _dnd_state["num_listeners"]; webview/util.py consumes the
        delivered objects per drop event). When pywebview's document-level
        handler fires it attaches each file's real path as
        "pywebviewFullPath" inside the event dict passed to the callback
        below, so the listener pushes a flux-dropped-paths event back into
        the page (same pattern as _emit_progress) for the frontend to
        resolve its dropped rows. Without this registration, drops still
        work in the UI but arrive without filesystem paths and cannot be
        converted.
        """

        def on_drop(event: dict) -> None:
            try:
                files = (event.get("dataTransfer") or {}).get("files") or []
                delivered = []
                for file in files:
                    if not isinstance(file, dict):
                        continue
                    path = file.get("pywebviewFullPath")
                    if isinstance(path, str) and path.strip():
                        delivered.append(
                            {
                                "name": file.get("name") or Path(path).name,
                                "path": path,
                                "size": file.get("size") or 0,
                            }
                        )
                if delivered:
                    self._emit_dropped_paths(delivered)
            except Exception:
                # Never let a drop-delivery problem break the drop itself.
                return

        try:
            window.dom.document.events.drop += DOMEventHandler(
                on_drop, prevent_default=False, stop_propagation=False
            )
        except Exception:
            # A failed registration only means dropped files arrive without
            # paths (name-only rows); the native picker flow is unaffected.
            pass

    def _emit_dropped_paths(self, files: list[dict[str, Any]]) -> None:
        window = self._window
        if window is None:
            return
        script = (
            "window.dispatchEvent(new CustomEvent('flux-dropped-paths', "
            f"{{detail: {json.dumps({'files': files})}}})) "
        )
        try:
            window.evaluate_js(script)
        except Exception:
            return

    def convert(
        self,
        files: list[Any] | dict[str, Any] | None = None,
        targetFormat: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(files, dict) and targetFormat is None:
            targetFormat = files.get("targetFormat")
            options = files.get("options") or {}
            files = files.get("files") or []

        if not isinstance(files, (list, tuple)) or not files:
            return self._error(
                "VALIDATION_ERROR",
                "Select at least one file to convert.",
            )

        if not isinstance(targetFormat, str) or not targetFormat.strip():
            return self._error(
                "VALIDATION_ERROR",
                "A target format is required.",
            )

        if not isinstance(options, dict):
            options = {}

        target = normalize_format(targetFormat)
        try:
            converter = self.registry.get_converter_for_format(target)
        except UnsupportedFormatError as exc:
            return self._error("UNSUPPORTED_FORMAT", str(exc), {"targetFormat": targetFormat})

        output_dir = options.get("outputDir") or options.get("output_dir")
        if not isinstance(output_dir, str) or not output_dir.strip():
            return self._error(
                "VALIDATION_ERROR",
                "An output directory is required.",
            )

        input_paths = self._input_paths(files)
        if input_paths is None:
            return self._error(
                "VALIDATION_ERROR",
                "Each file must include a readable path.",
            )

        output_directory = Path(output_dir).expanduser()
        if not output_directory.is_dir():
            return self._error(
                "VALIDATION_ERROR",
                "The output directory does not exist.",
                {"outputDir": output_dir},
            )

        job_id = uuid.uuid4().hex
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run_job,
            args=(
                job_id,
                converter,
                input_paths,
                str(output_directory),
                target,
                options,
                cancel_event,
            ),
            name=f"flux-convert-{job_id[:8]}",
            daemon=True,
        )
        job = _Job(
            job_id=job_id,
            thread=thread,
            converter=converter,
            cancel_event=cancel_event,
        )

        with self._lock:
            self._jobs[job_id] = job

        thread.start()
        return {"jobId": job_id}

    def getProgress(self, jobId: str) -> dict[str, Any]:
        if not isinstance(jobId, str):
            return self._error("NOT_FOUND", "Job not found.")

        with self._lock:
            job = self._jobs.get(jobId)
            if job is None:
                return self._error("NOT_FOUND", "Job not found.", {"jobId": jobId})

            response: dict[str, Any] = {
                "status": job.status,
                "progress": job.progress,
            }
            if job.output_paths:
                response["outputPaths"] = list(job.output_paths)
            if job.error:
                response["error"] = job.error

            if job.status in {"complete", "error"}:
                del self._jobs[jobId]

        return response

    def cancel(self, jobId: str) -> dict[str, Any]:
        if not isinstance(jobId, str):
            return self._error("NOT_FOUND", "Job not found.")

        with self._lock:
            job = self._jobs.get(jobId)
            if job is None:
                return self._error("NOT_FOUND", "Job not found.", {"jobId": jobId})

            if job.status in {"complete", "error"}:
                return self._error("ALREADY_COMPLETE", "Job is already complete.")

            job.cancel_event.set()

        return {"cancelled": True}

    def getSupportedFormats(self) -> dict[str, list[str]]:
        return {
            "input": self.registry.supported_input_formats,
            "output": self.registry.supported_output_formats,
        }

    def pickFiles(self, multiple: bool | dict[str, Any] = True) -> dict[str, Any]:
        if isinstance(multiple, dict):
            multiple = bool(multiple.get("multiple", True))

        window = self._window or webview.active_window()
        if window is None:
            return self._error("CANCELLED", "File selection was cancelled.")

        selection = window.create_file_dialog(
            dialog_type=webview.FileDialog.OPEN,
            allow_multiple=bool(multiple),
            file_types=("Image files (*.jpg;*.jpeg;*.png;*.webp)",),
        )
        # Single-select yields a bare string while multi-select yields a tuple:
        # iterating the string would otherwise produce one "path" per character.
        paths = _dialog_paths(selection)
        if not paths:
            return self._error("CANCELLED", "File selection was cancelled.")

        # Report name/size alongside the paths so the UI can render rows with
        # real sizes. A JS File object cannot be passed to Python: pywebview's
        # serializer only keeps own enumerable properties, and only dropped
        # files get a `pywebviewFullPath` attached.
        files = []
        for raw_path in paths:
            path = Path(raw_path)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            files.append({"path": str(path), "name": path.name, "size": size})

        return {"paths": [file["path"] for file in files], "files": files}

    def pickOutputDir(self) -> dict[str, Any]:
        window = self._window or webview.active_window()
        if window is None:
            return self._error("CANCELLED", "Output directory selection was cancelled.")

        # The folder dialog returns a single-element tuple, not a path: it must
        # be unwrapped, because str() would store the tuple's repr - the value
        # that made every later conversion fail with "The output directory does
        # not exist" (and that older builds persisted to localStorage).
        path = _first_path(window.create_file_dialog(dialog_type=webview.FileDialog.FOLDER))
        if path is None:
            return self._error("CANCELLED", "Output directory selection was cancelled.")

        return {"path": path}

    def openOutputDir(self, path: str | dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(path, dict):
            path = path.get("path")

        if not isinstance(path, str) or not path.strip():
            return self._error("VALIDATION_ERROR", "An output directory is required.")

        output_directory = Path(path).expanduser()
        if not output_directory.is_dir():
            return self._error("VALIDATION_ERROR", "The output directory does not exist.")

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(output_directory))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(output_directory)], check=False)
            else:
                subprocess.run(["xdg-open", str(output_directory)], check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return self._error("OPEN_ERROR", str(exc), {"path": str(output_directory)})

        return {"opened": True}

    # Cap for getFilePreview: the whole file crosses the bridge as base64, so
    # an unbounded read lets the page exhaust memory with one huge file.
    _MAX_PREVIEW_BYTES = 32 * 1024 * 1024

    # Read a file and return it as a base64 data URL for preview rendering.
    def getFilePreview(self, path: str | dict[str, Any] | None = None) -> dict[str, Any]:
        if isinstance(path, dict):
            path = path.get("path")

        if not isinstance(path, str) or not path.strip():
            return self._error("VALIDATION_ERROR", "A file path is required.")

        file_path = Path(path).expanduser()
        if not file_path.is_file():
            return self._error("VALIDATION_ERROR", "File does not exist.", {"path": path})

        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(file_path.suffix.lower())

        # Only known image types: the page must not be able to read arbitrary
        # local files (configs, documents, ...) through the preview bridge.
        if mime_type is None:
            return self._error(
                "VALIDATION_ERROR", "Only image files can be previewed.", {"path": path}
            )

        try:
            import base64

            with file_path.open("rb") as handle:
                data = handle.read(self._MAX_PREVIEW_BYTES + 1)
            if len(data) > self._MAX_PREVIEW_BYTES:
                return self._error(
                    "VALIDATION_ERROR", "File is too large to preview.", {"path": path}
                )
            b64 = base64.b64encode(data).decode("ascii")
            data_url = f"data:{mime_type};base64,{b64}"
            return {"dataUrl": data_url}
        except Exception as exc:
            return self._error("READ_ERROR", str(exc), {"path": path})

    # ------------------------------------------------------------------
    # In-app updates
    #
    # The bell button in the header drives three bridge calls. All network
    # work happens on Python threads; progress and terminal states are
    # pushed back as `flux-update-progress` CustomEvents (same pattern as
    # `flux-progress`), because the download outlives any single call.
    # ------------------------------------------------------------------

    # Wall-clock minimum between download-progress events: evaluate_js
    # blocks for a round-trip per call, so per-chunk events are coalesced.
    _UPDATE_EMIT_INTERVAL = 0.15

    def checkForUpdate(self) -> dict[str, Any]:
        """Check GitHub for a newer release than the running build.

        Returns the UpdateInfo payload (always containing currentVersion so
        the frontend can render an up-to-date state), or an error object for
        network failures - which the frontend treats as "no news" rather than
        something to bother the user about.
        """
        try:
            info = self._updater.check()
        except UpdateError as exc:
            return self._error(exc.code, exc.message)
        self._update_info = info
        return info.to_dict()

    def downloadUpdate(self) -> dict[str, Any]:
        """Start streaming the release installer; progress arrives via events.

        A second call while a download is running reports `started: true`
        instead of failing, so a double-click cannot wedge the UI into an
        error state for an action that is already underway.
        """
        info = self._update_info
        if info is None or not info.available:
            return self._error("NO_UPDATE", "No update is available.")
        if not self._download_lock.acquire(blocking=False):
            return {"started": True}

        threading.Thread(target=self._run_download, args=(info,), daemon=True).start()
        return {"started": True}

    def _run_download(self, info: UpdateInfo) -> None:
        try:
            path = self._updater.download(info, progress_cb=self._download_progress)
        except UpdateError as exc:
            self._emit_update_progress(
                {"phase": "error", "progress": 0, "code": exc.code, "message": exc.message}
            )
        except Exception as exc:  # defensive: never leave the UI hanging
            self._emit_update_progress(
                {
                    "phase": "error",
                    "progress": 0,
                    "code": "UNKNOWN",
                    "message": str(exc) or exc.__class__.__name__,
                }
            )
        else:
            self._downloaded_setup = path
            self._emit_update_progress({"phase": "downloaded", "progress": 100})
        finally:
            self._download_lock.release()

    def _download_progress(self, received: int, total: int) -> None:
        now = time.monotonic()
        if now - self._update_last_emit < self._UPDATE_EMIT_INTERVAL:
            return
        self._update_last_emit = now
        percentage = round((received / total) * 100) if total else 0
        self._emit_update_progress(
            {
                "phase": "downloading",
                "progress": max(0, min(100, percentage)),
                "received": received,
                "total": total,
            }
        )

    def _emit_update_progress(self, detail: dict[str, Any]) -> None:
        window = self._window
        if window is None:
            return
        script = (
            "window.dispatchEvent(new CustomEvent('flux-update-progress', "
            f"{{detail: {json.dumps(detail)}}}))"
        )
        try:
            window.evaluate_js(script)
        except Exception:
            return

    def installUpdate(self) -> dict[str, Any]:
        """Run the downloaded installer and close the app.

        The installer replaces the very files this process is executing
        from, so the sequence is: start the setup unattended (/SILENT - the
        script installs per-user with PrivilegesRequired=lowest, so there is
        no UAC prompt), then leave. Launching *before* the teardown matters:
        a timer scheduled at exit would be killed with the interpreter, and
        a launch strictly after exit would need a helper process. If Setup
        still finds locked files it closes them itself - silent mode never
        prompts - and relaunching after the upgrade is configured in the
        .iss script.
        """
        setup_path = self._downloaded_setup
        if setup_path is None or not Path(setup_path).is_file():
            return self._error("NOT_DOWNLOADED", "Download the update before installing it.")

        # Every release artifact is a Windows installer (installer/flux.iss), so
        # on any other platform there is nothing this action could run: refuse
        # instead of handing a foreign binary to the OS.
        if not sys.platform.startswith("win"):
            return self._error(
                "UNSUPPORTED_PLATFORM",
                "Installing an update from the app is only supported on Windows.",
            )

        # Windows-only from here on, so the unattended flags are unconditional.
        args = [str(setup_path), "/SILENT"]
        kwargs: dict[str, Any] = {
            "creationflags": (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        }
        try:
            subprocess.Popen(args, **kwargs)
        except OSError as exc:
            return self._error("INSTALL_ERROR", str(exc))

        # Give the bridge response a moment to reach the page before the
        # window (and with it the JS context) goes away.
        threading.Thread(target=self._destroy_window_for_update, daemon=True).start()
        return {"installing": True}

    def _destroy_window_for_update(self) -> None:
        time.sleep(0.4)
        window = self._window
        if window is None:
            os._exit(0)
        try:
            window.destroy()
        except Exception:
            # Nothing left to run; a hard exit still lets the already-started
            # installer finish the upgrade instead of hanging on a wedged
            # teardown.
            os._exit(0)

    def _run_job(
        self,
        job_id: str,
        converter: BaseConverter,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.progress = 0

        self._emit_progress(job_id)

        def progress_callback(current: int, total: int) -> None:
            percentage = round((current / total) * 100) if total else 0
            with self._lock:
                current_job = self._jobs.get(job_id)
                if current_job is None:
                    return
                current_job.progress = max(0, min(100, percentage))
            self._emit_progress(job_id)

        try:
            result = converter.convert(
                input_paths=input_paths,
                output_dir=output_dir,
                target_format=target_format,
                options=options,
                progress_cb=progress_callback,
                cancel_event=cancel_event,
            )
            self._finish_job(job_id, result, cancel_event.is_set())
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = "error"
                    job.error = str(exc) or exc.__class__.__name__
                    job.progress = 100 if job.progress else 0
            self._emit_progress(job_id)

    def _finish_job(self, job_id: str, result: ConversionResult, cancelled: bool) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return

            job.output_paths = list(result.output_paths)
            errors = "; ".join(result.errors)
            if cancelled:
                job.status = "error"
                job.error = errors or "Conversion cancelled"
            elif result.output_paths:
                # Partial success: finish as complete so the successful
                # outputs still reach the frontend; failures stay in job.error.
                job.status = "complete"
                job.error = errors or None
                job.progress = 100
            elif result.errors:
                job.status = "error"
                job.error = errors
            else:
                job.status = "complete"
                job.error = None
                job.progress = 100

        self._emit_progress(job_id)

    def _emit_progress(self, job_id: str) -> None:
        window = self._window
        if window is None:
            return

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            payload = {
                "jobId": job_id,
                "status": job.status,
                "progress": job.progress,
                "outputPaths": list(job.output_paths),
                "error": job.error,
            }

        script = (
            "window.dispatchEvent(new CustomEvent('flux-progress', "
            f"{{detail: {json.dumps(payload)}}}))"
        )
        try:
            window.evaluate_js(script)
        except Exception:
            return

    @staticmethod
    def _input_paths(files: list[Any]) -> list[str] | None:
        paths: list[str] = []
        for file in files:
            if isinstance(file, str):
                path = file
            elif isinstance(file, dict):
                # Dropped files arrive without a path: the frontend resolves
                # them against pywebview's delivered path list before calling
                # (see consumeDroppedPaths), so only "path" is supported here.
                path = file.get("path")
            else:
                path = getattr(file, "path", None) or getattr(
                    file, "pywebviewFullPath", None
                )

            if not isinstance(path, str) or not path.strip():
                return None
            paths.append(path)
        return paths

    @staticmethod
    def _error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        response: dict[str, Any] = {"code": code, "message": message}
        if details:
            response["details"] = details
        return response


API = FluxAPI
FluxApi = FluxAPI