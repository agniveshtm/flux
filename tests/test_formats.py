"""The frontend's copy of the format lists must match the backend's.

Phase 1.1 replaced the hardcoded TARGETS_BY_INPUT table with a matrix derived
from getSupportedFormats(), so the backend's converters are now the single
source of truth for what Flux supports. Three things still shadow them on the
JS side, and none fails loudly on its own:

* useFlux.js's mockSupportedFormats - the browser-dev stand-in, also used as the
  pre-load fallback for input validation. If it drifts, a file dropped during
  startup is silently rejected for a format Flux does support.
* window.py's pickFiles dialog filter and getFilePreview MIME map, which are
  what make the new formats selectable and previewable at all.
* The mock's input->target matrix, which mirrors the registry's
  supported_targets_by_input for browser dev, and its `rings` map, which
  mirrors supported_output_rings for the format donut (GIF belongs to the
  video ring as well as the image one).

A new format added to a converter but not to these lists produces an app that
converts correctly but cannot be told to, so the drift is pinned here. Video
entries are gated on video_available() the way AVIF/HEIF are gated on their
encoders: the mock is a static literal, the registry is not, and only the
backend list legitimately shrinks on a build without ffmpeg.
"""

from __future__ import annotations

import re
from pathlib import Path

from flux.converter import normalize_format
from flux.services.ffmpeg import VIDEO_INPUT_FORMATS, video_available
from flux.services.image_converter import (
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    _avif_available,
    _heif_available,
)
from flux.window import FluxAPI

REPO_ROOT = Path(__file__).resolve().parents[1]
USE_FLUX = REPO_ROOT / "src" / "flux" / "frontend" / "composables" / "useFlux.js"
WINDOW = REPO_ROOT / "src" / "flux" / "window.py"
MAIN_JS = REPO_ROOT / "src" / "flux" / "frontend" / "main.js"


def _js_format_lists() -> dict[str, list[str]]:
    """Pull mockSupportedFormats' input/output arrays out of useFlux.js."""
    source = USE_FLUX.read_text(encoding="utf-8")
    match = re.search(
        r"const mockSupportedFormats\s*=\s*\{(?P<body>.*?)\};", source, re.DOTALL
    )
    assert match, "mockSupportedFormats not found in useFlux.js"

    lists: dict[str, list[str]] = {}
    for key, values in re.findall(r"(input|output)\s*:\s*\[([^\]]*)\]", match.group("body")):
        lists[key] = re.findall(r"['\"]([^'\"]+)['\"]", values)

    assert set(lists) == {"input", "output"}, f"unexpected keys: {sorted(lists)}"
    return lists


def _js_format_kinds() -> dict[str, str]:
    """Pull mockSupportedFormats' kinds map out of useFlux.js."""
    source = USE_FLUX.read_text(encoding="utf-8")
    match = re.search(r"kinds\s*:\s*\{(?P<body>[^}]*)\}", source, re.DOTALL)
    assert match, "mockSupportedFormats.kinds not found in useFlux.js"
    return dict(
        re.findall(r"['\"]?([A-Za-z0-9_]+)['\"]?\s*:\s*['\"]([^'\"]+)['\"]", match.group("body"))
    )


def _js_format_rings() -> dict[str, list[str]]:
    """Pull mockSupportedFormats' rings map out of useFlux.js."""
    source = USE_FLUX.read_text(encoding="utf-8")
    match = re.search(r"rings\s*:\s*\{(?P<body>[^}]*)\}", source, re.DOTALL)
    assert match, "mockSupportedFormats.rings not found in useFlux.js"
    return {
        kind: re.findall(r"['\"]([^'\"]+)['\"]", items)
        for kind, items in re.findall(r"(\w+)\s*:\s*\[([^\]]*)\]", match.group("body"))
    }


def test_frontend_mock_matches_backend_formats() -> None:
    lists = _js_format_lists()
    inputs, outputs = lists["input"], lists["output"]

    if not _avif_available():
        # The frontend mock is a static literal, but the real matrix is derived
        # from the bridge at runtime, so on a build without libavif a stale
        # AVIF entry in the dev mock cannot reach the user. Only the backend
        # list legitimately shrinks.
        inputs = [item for item in inputs if item != "avif"]
        outputs = [item for item in outputs if item != "avif"]

    if not _heif_available():
        # Same gate logic as AVIF: pillow-heif may be absent, and the mock
        # staying static would advertise formats the app cannot handle.
        inputs = [item for item in inputs if item not in ("heic", "heif")]
        outputs = [item for item in outputs if item != "heic"]

    expected_inputs = list(INPUT_FORMATS)
    expected_outputs = list(OUTPUT_FORMATS)
    if video_available():
        # Video is a capability gate, not a compile-time constant: the registry
        # only exposes it when the local ffmpeg can encode, and the mock lists
        # it unconditionally, so the surplus entries are tolerated exactly the
        # way a stale AVIF entry is above.
        expected_inputs += list(VIDEO_INPUT_FORMATS)
        expected_outputs += ["mp4"]
    else:
        inputs = [item for item in inputs if item not in VIDEO_INPUT_FORMATS]
        outputs = [item for item in outputs if item != "mp4"]

    assert inputs == expected_inputs
    assert outputs == expected_outputs


def test_mock_video_inputs_match_the_backend() -> None:
    """The mock's `videoInputs` dev-parity list is ffmpeg's video containers.

    The frontend uses it to decide which dropped files get a video row in
    browser dev, so a drift here shows up as a clip silently joining the image
    batch (or never arriving at all) when running against the mock.
    """
    source = USE_FLUX.read_text(encoding="utf-8")
    match = re.search(
        r"videoInputs\s*:\s*\[(?P<items>[^\]]*)\]", source, re.DOTALL
    )
    assert match, "mockSupportedFormats.videoInputs not found in useFlux.js"
    video_inputs = re.findall(r"['\"]([^'\"]+)['\"]", match.group("items"))

    assert video_inputs == list(VIDEO_INPUT_FORMATS)

    lists = _js_format_lists()
    for fmt in VIDEO_INPUT_FORMATS:
        assert fmt in lists["input"], f"mock input list is missing video format {fmt}"


def test_frontend_mock_kinds_match_the_backend() -> None:
    """The kinds map must cover exactly the formats the backend can write.

    The UI groups the formats it offers by kind - the format picker shows
    image and video formats as separate sets - so the mock's map is a second
    copy of the backend's converter registry. If a format is missing from it
    the picker would drop that format; if it names a format the backend
    cannot write, the picker would offer a target that does not exist.
    """
    kinds = _js_format_kinds()

    expected_outputs = set(OUTPUT_FORMATS)
    expected_values = {"image"}
    if video_available():
        expected_outputs.add("mp4")
        expected_values.add("video")
    else:
        kinds = {fmt: kind for fmt, kind in kinds.items() if fmt != "mp4"}

    assert set(kinds) == expected_outputs, (
        f"mock kinds cover {sorted(kinds)}, backend outputs {sorted(expected_outputs)}"
    )
    assert set(kinds.values()) == expected_values, (
        "kinds must report exactly the converter registry's kinds ('image', plus "
        "'video' when ffmpeg is available); anything else would group a format "
        "under a picker section the backend cannot write"
    )
    if video_available():
        assert kinds["mp4"] == "video", "MP4 must be grouped as a video format"


def test_picker_offers_every_supported_input_format() -> None:
    # pickFiles is what puts a file into the list, so a format missing from its
    # filter can never be selected through the native picker at all. The filter
    # is now two static entries (images and videos), so the regex has to read
    # past the first entry's closing paren instead of stopping there.
    source = WINDOW.read_text(encoding="utf-8")
    match = re.search(
        r"file_types=\((?P<patterns>.*?)\n\s+\),", source, re.DOTALL
    )
    assert match, "pickFiles file_types filter not found"

    patterns = match.group("patterns")
    for fmt in (*INPUT_FORMATS, *VIDEO_INPUT_FORMATS):
        assert f"*.{fmt}" in patterns, f"pickFiles filter is missing *.{fmt}"


def test_image_inputs_are_previewable_and_video_inputs_are_not() -> None:
    # getFilePreview is an explicit allowlist, and it is also the guard that
    # stops the page reading arbitrary local files - so it must cover every
    # image the converter accepts, no more and no less. Video inputs are the
    # deliberate exception: a clip has no meaningful still frame to show, and
    # decoding one per row would cost more than the thumbnail is worth, so the
    # file row falls back to its glyph instead.
    api = FluxAPI()
    for fmt in INPUT_FORMATS:
        assert api._mime_type_for(f".{fmt}") is not None, f"no preview MIME type for .{fmt}"

    for fmt in VIDEO_INPUT_FORMATS:
        assert api._mime_type_for(f".{fmt}") is None, (
            f".{fmt} must not be previewable; a MIME type here would make the "
            "page hand a video to <img> as if it were a still"
        )

    assert api._mime_type_for(".pdf") is None
    assert api._mime_type_for(".txt") is None


def test_preview_allowlist_admits_nothing_the_converter_cannot_read() -> None:
    # The reverse direction, which the test above does not check. The map used
    # to carry .bmp, .tif and .tiff - formats Flux cannot convert - so the page
    # could preview a file the app would then refuse, and the allowlist was
    # wider than the boundary it was meant to describe. Both directions are now
    # pinned so the two lists cannot drift apart again. The video inputs are
    # outside the boundary on purpose (see the test above), so this compares
    # against the image inputs, which is what the map has always been for.
    allowed = {suffix.lstrip(".") for suffix in FluxAPI._PREVIEW_MIME_TYPES}

    # .avif is defensible in either direction: it is in INPUT_FORMATS whenever
    # this build can read it, and the static map keeps it when it cannot.
    expected = set(INPUT_FORMATS)
    assert allowed == expected or allowed == expected - {"avif"} or allowed == expected | {"avif"}, (
        f"preview allowlist {sorted(allowed)} does not match the readable formats "
        f"{sorted(expected)}"
    )


def test_conversion_matrix_is_derived_not_hardcoded() -> None:
    """The registry pairs each input with the outputs that can read it.

    This is the behaviour that replaced TARGETS_BY_INPUT, and it has to hold in
    the direction that matters for MP4: re-encoding a file to the format it is
    already in is a no-op, so a format is never offered as a target of itself,
    and a target is only offered when its own converter also reads that input -
    which is why image rows never gain an MP4 option (the video converter
    decodes no stills) and video rows gain every image target (frames are
    extracted first). The completeness half keeps the pairing from collapsing
    to "nothing", which would also satisfy every exclusivity rule above.
    """
    registry = FluxAPI().registry
    mapping = registry.supported_targets_by_input
    assert mapping, "the registry derived no input->targets pairs"

    for input_format, targets in mapping.items():
        key = normalize_format(input_format)
        assert key not in targets, f"{input_format} must not be a target of itself"
        for target in targets:
            converter = registry.get_converter_for_format(target)
            assert input_format in converter.supported_input_formats, (
                f"target {target} is offered for {input_format} but its "
                "converter cannot read that input"
            )

    image_outputs = set(OUTPUT_FORMATS)
    for fmt in INPUT_FORMATS:
        targets = set(mapping[fmt])
        # Every image the app writes stays reachable from every image it reads,
        # minus the self-pairing - and never MP4, whose converter refuses
        # stills rather than emitting a one-frame clip.
        assert image_outputs - {normalize_format(fmt)} <= targets, (
            f"{fmt} lost image targets: {sorted(targets)}"
        )
        if fmt == "gif" and video_available():
            # The one exception to "no MP4 from a still": a GIF *is* an
            # animation, and the video converter reads it (gif -> mp4), so
            # its row offers MP4 alongside every image target.
            assert "mp4" in targets, "gif should offer MP4 like a video input"
        else:
            assert "mp4" not in targets, f"{fmt} must not offer MP4 from a still image"

    if video_available():
        for fmt in VIDEO_INPUT_FORMATS:
            targets = set(mapping[fmt])
            if fmt != "mp4":
                assert "mp4" in targets, f"{fmt} should offer MP4"
            # A clip converts to a still too: the image converter extracts the
            # first frame and runs the whole quality pipeline over it.
            assert image_outputs <= targets, (
                f"{fmt} lost frame-extraction targets: {sorted(targets)}"
            )


def _target_preference() -> list[str]:
    """Pull TARGET_PREFERENCE's entries out of main.js."""
    source = MAIN_JS.read_text(encoding="utf-8")
    match = re.search(
        r"const TARGET_PREFERENCE\s*=\s*\[(?P<items>[^\]]*)\]", source
    )
    assert match, "TARGET_PREFERENCE not found in main.js"
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group("items"))


def test_default_target_is_not_avif() -> None:
    """TARGET_PREFERENCE must keep AVIF last and cover every output format.

    `getDefaultTargetFormat` used to return `targetsForInput(ext)[0]`, and
    because the matrix is derived from `getSupportedFormats()` - which returns
    sorted lists - that is the alphabetically first target: 'avif' for every
    input except AVIF itself. Every file a user dropped was therefore preloaded
    for the slowest encoder here and the least compatible output, before they
    had chosen anything, and the quality slider appeared with it.

    `TARGET_PREFERENCE` now states the order explicitly and `defaultTargetFor`
    walks it. This test pins the *list*; the wiring is verified separately by
    `scripts/check-frontend.js`, which executes the real `defaultTargetFor` and
    asserts `getDefaultTargetFormat` calls it. Parsing the source here cannot
    catch a regression in that wiring, so the two are complementary:
    re-introducing `targets[0]` leaves this test green.
    """
    preference = _target_preference()
    outputs = list(OUTPUT_FORMATS)
    if video_available():
        # MP4 has to be in the preference too, or a video row's only video
        # target would fall through to the alphabetical first target.
        outputs = [*outputs, "mp4"]

    assert set(outputs) <= set(preference), (
        f"TARGET_PREFERENCE is missing {sorted(set(outputs) - set(preference))}, "
        "so those formats fall back to the alphabetical first target"
    )
    assert preference[-1] == "avif", (
        f"'avif' must stay last in TARGET_PREFERENCE (got {preference}); "
        "an earlier position makes it some input's silent default"
    )
    # No format may appear twice: the first occurrence would win and the second
    # would be dead weight that reads as part of the ordering.
    assert len(preference) == len(set(preference)), (
        f"TARGET_PREFERENCE has duplicates: {preference}"
    )

    for fmt in INPUT_FORMATS:
        targets = [out for out in OUTPUT_FORMATS if out != normalize_format(fmt)]
        expected = next(out for out in preference if out in targets)
        assert expected != "avif" or targets == ["avif"], (
            f"{fmt} would preselect 'avif' although {targets} are available"
        )

    if video_available():
        # A GIF row is the mirror image of a video row: GIF is an animation,
        # MP4 is first in the preference, and MP4 is one of its targets - so
        # a gif input must preselect MP4, not the first still target.
        gif_targets = [out for out in OUTPUT_FORMATS if out != "gif"] + ["mp4"]
        expected = next(out for out in preference if out in gif_targets)
        assert expected == "mp4", (
            f"a gif input would preselect '{expected}' although MP4 is available"
        )

        # A non-MP4 video row must land on MP4. Every other target for a clip
        # is a still-frame extraction, so preselecting one would silently hand
        # the user an image - and 'jpg' is exactly what the alphabetical first
        # target resolved to before the preference included 'mp4'. An .mp4 row
        # is the mirror image: MP4 is its own format, so it must land on a
        # frame extraction rather than looping back to itself.
        for fmt in VIDEO_INPUT_FORMATS:
            targets = list(OUTPUT_FORMATS)
            if fmt != "mp4":
                targets.append("mp4")
            expected = next(out for out in preference if out in targets)
            if fmt == "mp4":
                assert expected in OUTPUT_FORMATS, (
                    f"an .mp4 input would preselect '{expected}', which is "
                    "not a frame-extraction target"
                )
            else:
                assert expected == "mp4", (
                    f"a {fmt} input would preselect '{expected}' although "
                    "MP4 is available"
                )


def test_mock_rings_match_the_backend_registry() -> None:
    """The donut's ring grouping is backend-owned; the mock mirrors it.

    FormatDonut renders exactly what getSupportedFormats().rings says, and
    the mock is the payload it renders before the bridge (and in browser
    dev). The point of the pairing is GIF: it sits in the image ring (a
    gif -> gif still is an image conversion) *and* in the video ring (gif
    -> mp4 reads it as an animation, mp4 -> gif writes one), so the second
    ring is not just "the video outputs" any more.
    """
    rings = _js_format_rings()
    backend = FluxAPI().registry.supported_output_rings

    # The mock is a static literal: entries whose converter is capability-
    # gated away are tolerated the same way a stale AVIF input is.
    if not _avif_available():
        rings["image"] = [fmt for fmt in rings["image"] if fmt != "avif"]
    if not _heif_available():
        rings["image"] = [fmt for fmt in rings["image"] if fmt != "heic"]
    if not video_available():
        rings["video"] = []

    assert set(rings) == {"image", "video"}, f"unexpected rings: {sorted(rings)}"
    assert sorted(rings["image"]) == sorted(backend["image"]), (
        f"mock image ring {sorted(rings['image'])} != backend {sorted(backend['image'])}"
    )
    assert sorted(rings["video"]) == sorted(backend["video"]), (
        f"mock video ring {sorted(rings['video'])} != backend {sorted(backend['video'])}"
    )

    every_output = set(backend["image"]) | set(backend["video"])
    assert set(rings["image"]) | set(rings["video"]) == every_output, (
        "the two rings together must cover every format the backend can write"
    )
    if video_available():
        # The whole reason rings exist: GIF belongs to both, MP4 to video only.
        assert "gif" in rings["image"] and "gif" in rings["video"]
        assert "mp4" in rings["video"] and "mp4" not in rings["image"]
    else:
        assert rings["video"] == []


def test_get_supported_formats_carries_the_ring_grouping() -> None:
    """window.py ships the rings on the same payload as kinds and targets.

    The donut cannot group what it never receives: without this key
    FormatDonut falls back to kinds, which has no idea GIF is also a video
    conversion - so the payload key itself is pinned, not just its source.
    """
    payload = FluxAPI().getSupportedFormats()

    assert "rings" in payload, "getSupportedFormats() does not carry rings"
    rings = payload["rings"]
    assert rings == FluxAPI().registry.supported_output_rings
    assert set(rings["image"]) | set(rings["video"]) == set(payload["output"])

    if video_available():
        assert "gif" in rings["image"] and "gif" in rings["video"]
        assert "mp4" in rings["video"] and "mp4" not in rings["image"]
    else:
        assert rings["video"] == []


def test_mock_matrix_offers_mp4_for_gif_inputs() -> None:
    """The mock's matrix builder gives GIF's row the MP4 target.

    The backend side of this is pinned by test_conversion_matrix (the gif
    input row contains mp4); this pins the mock's computed copy, which is
    built by hand in useFlux.js rather than derived. Without the line, the
    two matrices disagree for exactly one input and gif -> mp4 silently
    exists only where the registry does.
    """
    source = USE_FLUX.read_text(encoding="utf-8")
    assert "takesMp4 = isVideo || input === 'gif'" in source, (
        "the mock's targets builder no longer offers MP4 for gif inputs"
    )

    mapping = FluxAPI().registry.supported_targets_by_input
    if video_available():
        assert "mp4" in mapping["gif"], "the backend gif row must offer MP4"
    else:
        assert "mp4" not in mapping["gif"]
