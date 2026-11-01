"""FFmpegVideoConverter: video conversion to MP4, WebM, MKV, MOV and AVI.

Implements BaseConverter against the bundled ffmpeg sidecar binary. The
ffmpeg process is invoked over argv + pipes (subprocess), never linked -
which is what keeps the LGPL/GPL from reaching Flux's own code (see
research/phase2-video-mobile/REPORT.md 1.2.1: pipes and argv are
communication between two separate programs, not linking).

The researched process behaviours - progress parsing, continuous stdout
drain, the three-rung cancel chain, duration from stderr instead of
ffprobe - live once in flux.services.ffmpeg.run_ffmpeg, shared with the
image converter's video-to-GIF encode and the audio converter. This module
owns what is container-specific: the encoder preference table, the CRF
mappings, the audio pairing and the muxer flags.

Inputs cover the video containers plus GIF, which the video converter reads
as an animation source (GIF -> MP4) - GIF is written as an image format by
the image converter, and read as a video by this one. Outputs are
capability-gated per container (see flux.services.ffmpeg).
"""

from __future__ import annotations

from threading import Event
from typing import Callable

from flux.converter import (
    BaseConverter,
    ConversionResult,
    UnsupportedFormatError,
    clamp_quality,
    convert_files,
    normalize_format,
)
from flux.services.ffmpeg import (
    VIDEO_INPUT_FORMATS,
    VIDEO_OUTPUT_FORMATS,
    locate_ffmpeg,
    run_ffmpeg,
    video_available,
    video_encoder_for,
    video_output_available,
)

# Every video output, in the researched matrix's order. The frontend never
# keeps this list: the registry derives the matrix and rings from the
# converter that writes each format.
OUTPUT_FORMATS = VIDEO_OUTPUT_FORMATS


def x264_crf(quality: int | None) -> int:
    """Slider value -> libx264 CRF on the sane 18-28 window (default 23).

    Lower CRF is better quality: 100 -> 18 (near lossless), 0 -> 28, and
    the untouched default lands on x264's own default of 23.
    """
    if quality is None:
        return 23
    return 28 - (clamp_quality(quality) * 10) // 100


def vp9_crf(quality: int | None) -> int:
    """Slider value -> libvpx-vp9 CRF (0-63 scale, sane window 10-40).

    Not x264's scale - the two are not interchangeable - and the default
    (None) is libvpx's own recommended 32 with -b:v 0 for quality mode.
    """
    if quality is None:
        return 32
    return 40 - (clamp_quality(quality) * 30) // 100


def video_encode_args(encoder: str, quality: int | None) -> list[str]:
    """The video-side command line for one encoder.

    One table keyed on encoder name is the whole per-codec divergence: CRF
    ranges differ (x264 0-51, VP9 0-63), VP9 needs -b:v 0 to mean "CRF
    mode", and only x264 has presets. Everything else about MP4 output -
    pixel format, faststart - is identical and lives in _encode_one.
    """
    if encoder == "libx264":
        return [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(x264_crf(quality)),
            "-pix_fmt", "yuv420p",
        ]
    if encoder == "libvpx-vp9":
        return [
            "-c:v", "libvpx-vp9",
            "-crf", str(vp9_crf(quality)),
            "-b:v", "0",
            "-row-mt", "1",
            "-deadline", "good",
            # Speed tier, fixed rather than slider-driven: the slider means
            # quality, and letting it also change encode speed would make the
            # same number mean two things. 4 is the mid-fast point of 0-5.
            "-cpu-used", "4",
            "-pix_fmt", "yuv420p",
        ]
    raise UnsupportedFormatError(f"No video encode arguments for encoder: {encoder}")


def video_audio_args(target_format: str) -> list[str]:
    """The audio half of one container's command line.

    WebM and MKV pair with Opus (the royalty-free pairing the research
    report recommends); every other container keeps AAC, which is the
    universally decodable pairing MP4 already used. This is the same table
    capability gating reads (VIDEO_AUDIO_ENCODERS), so the codec that is
    checked for is the codec that is written.
    """
    if target_format in ("webm", "mkv"):
        return ["-c:a", "libopus", "-b:a", "128k"]
    return ["-c:a", "aac", "-b:a", "128k"]


# Bytes reserved at the head of each AVI stream for its OpenDML superindex.
# The research table said "16M", but that is a per-stream JUNK chunk before
# the stream headers: on ffmpeg 9.0.2 a 16 MiB reserve pushes the second
# stream's `strl` past the demuxer's header window, so the audio stream
# silently vanishes and `-v error` reports "tag JUNK has size ...". The
# superindex itself is ~16 bytes per GiB of file, so 64 KiB covers a 4 TiB
# AVI with room to spare and stays well inside the parser's limit.
AVI_INDEX_RESERVE_BYTES = 65536


def container_args(target_format: str) -> list[str]:
    """Muxer flags specific to one container, or an empty list.

    MP4 gets +faststart so playback can begin before the whole file
    downloads. MOV is otherwise the same command but deliberately without
    it; AVI gets a modest reserve_index_space so a long file can still seek
    reliably (see AVI_INDEX_RESERVE_BYTES for why it is not the research
    table's 16M); MKV and WebM need nothing beyond the codec choice.
    """
    if target_format == "mp4":
        return ["-movflags", "+faststart"]
    if target_format == "avi":
        return ["-reserve_index_space", str(AVI_INDEX_RESERVE_BYTES)]
    return []


class FFmpegVideoConverter(BaseConverter):
    @property
    def kind(self) -> str:
        return "video"

    @property
    def supported_input_formats(self) -> list[str]:
        # Capability-gated: with no capable ffmpeg build this returns an
        # empty list, the registry maps no formats to this converter, and
        # the UI never offers video conversion - the same pattern as the
        # AVIF/HEIF gates in image_converter, so a source checkout without
        # vendor/ffmpeg.exe runs exactly as it did before video.
        #
        # GIF joins the containers because ffmpeg reads it as an animation
        # and this converter writes a real video from it - while the image
        # converter keeps reading GIF through Pillow for every still target.
        if not self.supported_output_formats:
            return []
        return [*VIDEO_INPUT_FORMATS, "gif"]

    @property
    def supported_output_formats(self) -> list[str]:
        """The containers this build can actually write.

        Gating is per output rather than all-or-nothing: a build with VP9
        but no libx264 still writes WebM, and a build missing libopus simply
        does not offer WebM/MKV. With no video encoder at all the list is
        empty and the converter registers nothing.
        """
        if not video_available():
            return []
        return [fmt for fmt in OUTPUT_FORMATS if video_output_available(fmt)]

    def convert(
        self,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict,
        progress_cb: Callable[[float, float], None],
        cancel_event: Event,
    ) -> ConversionResult:
        target = normalize_format(target_format)
        if target not in self.supported_output_formats:
            raise UnsupportedFormatError(f"Unsupported output format: {target_format}")

        encoder = video_encoder_for(target)
        ffmpeg = locate_ffmpeg()
        if encoder is None or ffmpeg is None:
            return ConversionResult(
                errors=["Video conversion is unavailable: no capable ffmpeg build was found."]
            )

        conversion_options = options if isinstance(options, dict) else {}

        def encode_one(
            source: Path,
            output_path: Path,
            completed_before: int,
            total: float,
        ) -> tuple[bool, str | None]:
            return self._encode_one(
                ffmpeg=ffmpeg,
                encoder=encoder,
                target_format=target,
                source=source,
                output_path=output_path,
                options=conversion_options,
                progress_cb=progress_cb,
                completed_before=completed_before,
                total=total,
                cancel_event=cancel_event,
            )

        return convert_files(
            input_paths=input_paths,
            output_dir=output_dir,
            target_format=target,
            allowed_input_formats=self.supported_input_formats,
            encode_one=encode_one,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def _encode_one(
        self,
        ffmpeg: Path,
        encoder: str,
        target_format: str,
        source: Path,
        output_path: Path,
        options: dict,
        progress_cb: Callable[[float, float], None],
        completed_before: int,
        total: float,
        cancel_event: Event,
    ) -> tuple[bool, str | None]:
        """Run one ffmpeg encode. Returns (success, error_message).

        Command shape (verified against the report's per-phase table):
        -progress pipe:1 puts machine-readable key=value lines on stdout;
        -nostats silences the human-readable stats line so stderr stays a
        small parseable log (where -loglevel info yields the Duration);
        -stats_period 0.25 doubles the tick rate for a smoother bar; -y
        overwrites the 0-byte placeholder reserve_unique_output claimed (the
        claim, not -y, is the race guard).

        Progress, the stdout drain and the three-rung cancel chain are the
        shared engine's job (flux.services.ffmpeg.run_ffmpeg). Everything
        container-specific is one of the three tables below: the codec's
        own CRF scale, the container's audio pairing, and its muxer flags.
        """
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-nostats",
            "-loglevel", "info",
            "-stats_period", "0.25",
            "-progress", "pipe:1",
            "-y",
            "-i", str(source),
            *video_encode_args(encoder, options.get("quality")),
            *video_audio_args(target_format),
            *container_args(target_format),
            str(output_path),
        ]

        return run_ffmpeg(
            cmd,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            completed_before=completed_before,
            total=total,
            expected_output=output_path,
        )
