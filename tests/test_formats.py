"""The frontend's copy of the format lists must match the backend's.

Phase 1.1 replaced the hardcoded TARGETS_BY_INPUT table with a matrix derived
from getSupportedFormats(), so the backend's converters are now the single
source of truth for what Flux supports. Three things still shadow them on the
JS side, and none fails loudly on its own:

* useFlux.js's mockSupportedFormats - the browser-dev stand-in, also used as the
  pre-load fallback for input validation. If it drifts, a file dropped during
  startup is silently rejected for a format Flux does support.
* window.py's pickFiles dialog filter and getFilePreview allowlists, which are
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
from flux.services.ffmpeg import (
    AUDIO_OUTPUT_FORMATS,
    VIDEO_INPUT_FORMATS,
    VIDEO_OUTPUT_FORMATS,
    audio_encoder_for,
    video_available,
    video_output_available,
)
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


def _available_video_outputs() -> list[str]:
    """The video containers this build can write, in matrix order."""
    return [fmt for fmt in VIDEO_OUTPUT_FORMATS if video_output_available(fmt)]


def _available_audio_outputs() -> list[str]:
    """The audio targets this build can write, in matrix order."""
    return [
        fmt for fmt in AUDIO_OUTPUT_FORMATS if audio_encoder_for(fmt) is not None
    ]


def _strip_unavailable_from_mock(items: list[str]) -> list[str]:
    """Drop video/audio entries whose encoder this build does not have.

    The mock is a static literal while the registry is capability-gated
    (exactly like AVIF/HEIC), so a build missing an encoder legitimately
    shrinks the backend side and the mock side is trimmed to match.
    """
    available_video = set(_available_video_outputs())
    available_audio = set(_available_audio_outputs())
    return [
        item for item in items
        if (item not in VIDEO_OUTPUT_FORMATS or item in available_video)
        and (item not in AUDIO_OUTPUT_FORMATS or item in available_audio)
    ]


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
    if video_available() or _available_audio_outputs():
        # Video containers are readable when *either* ffmpeg converter
        # exists: the video converter transcodes them, the audio converter
        # extracts their soundtrack, and the image converter pulls a frame.
        # Video and audio outputs themselves are gated per encoder - a build
        # with VP9 but no libopus writes WebM's video but not its audio half,
        # so it does not offer the container at all.
        expected_inputs += list(VIDEO_INPUT_FORMATS)
        expected_outputs += _available_video_outputs()
        expected_outputs += _available_audio_outputs()
    else:
        # No ffmpeg at all: the mock's static video/audio entries are the
        # surplus a stale AVIF entry is, trimmed off the mock side.
        inputs = [item for item in inputs if item not in VIDEO_INPUT_FORMATS]
        outputs = _strip_unavailable_from_mock(outputs)

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

    The UI groups the formats it offers by kind - the format picker cycles
    through image, video and audio rings - so the mock's map is a second copy
    of the backend's converter registry. If a format is missing from it the
    picker would drop that format; if it names a format the backend cannot
    write, the picker would offer a target that does not exist.
    """
    kinds = _js_format_kinds()

    if not _avif_available():
        # Same tolerance as test_frontend_mock_matches_backend_formats: the
        # mock's kinds map is a static literal, while OUTPUT_FORMATS below is
        # gated on the local Pillow build, so a format this build cannot write
        # has to come off the mock side of the comparison.
        kinds.pop("avif", None)
    if not _heif_available():
        kinds.pop("heic", None)

    video_outputs = _available_video_outputs()
    audio_outputs = _available_audio_outputs()

    expected_outputs = set(OUTPUT_FORMATS) | set(video_outputs) | set(audio_outputs)
    expected_values = {"image"}
    if video_outputs:
        expected_values.add("video")
    if audio_outputs:
        expected_values.add("audio")

    # A format this build cannot write is stripped from the static mock side.
    unavailable = (
        set(VIDEO_OUTPUT_FORMATS) - set(video_outputs)
    ) | (set(AUDIO_OUTPUT_FORMATS) - set(audio_outputs))
    kinds = {fmt: kind for fmt, kind in kinds.items() if fmt not in unavailable}

    assert set(kinds) == expected_outputs, (
        f"mock kinds cover {sorted(kinds)}, backend outputs {sorted(expected_outputs)}"
    )
    assert set(kinds.values()) == expected_values, (
        "kinds must report exactly the converter registry's kinds ('image', plus "
        "'video' and 'audio' when their encoders are available); anything else "
        "would group a format under a picker ring the backend cannot write"
    )
    for fmt in video_outputs:
        assert kinds[fmt] == "video", f"{fmt} must be grouped as a video format"
    for fmt in audio_outputs:
        assert kinds[fmt] == "audio", f"{fmt} must be grouped as an audio format"


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


def test_image_inputs_are_previewable_and_video_inputs_get_a_frame() -> None:
    # getFilePreview is an explicit allowlist, and it is also the guard that
    # stops the page reading arbitrary local files - so it must cover every
    # input the converters accept, no more and no less. Images get a MIME type
    # and go through Pillow; videos must *not* get one (that would hand a clip
    # to <img>), they go through ffmpeg for a poster frame instead.
    api = FluxAPI()
    for fmt in INPUT_FORMATS:
        assert api._mime_type_for(f".{fmt}") is not None, f"no preview MIME type for .{fmt}"

    for fmt in VIDEO_INPUT_FORMATS:
        assert api._mime_type_for(f".{fmt}") is None, (
            f".{fmt} must not have an image MIME type; the page would hand a "
            "video to <img> as if it were a still"
        )
        assert api._is_video_preview(f".{fmt}"), f".{fmt} must be previewable as a video"

    assert api._is_video_preview(".pdf") is False
    assert api._mime_type_for(".pdf") is None
    assert api._mime_type_for(".txt") is None
    assert api._is_video_preview(".txt") is False


def test_preview_allowlist_admits_nothing_the_converter_cannot_read() -> None:
    # The reverse direction, which the test above does not check. The map used
    # to carry .bmp, .tif and .tiff - formats Flux cannot convert - so the page
    # could preview a file the app would then refuse, and the allowlist was
    # wider than the boundary it was meant to describe. Both directions are now
    # pinned so the two lists cannot drift apart again. Video inputs are the
    # separate ffmpeg-frame allowlist (see the test above), so this compares
    # against the image inputs, which is what the MIME map is for.
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
    the direction that matters for the video outputs: re-encoding a file to the
    format it is already in is a no-op, so a format is never offered as a
    target of itself, and a target is only offered when its own converter also
    reads that input - which is why image rows never gain MP4/WebM/MP3 (the
    video and audio converters decode no stills) and video rows gain every
    image target (frames are extracted first). The completeness half keeps the
    pairing from collapsing to "nothing", which would also satisfy every
    exclusivity rule above.
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
    video_outputs = set(_available_video_outputs())
    audio_outputs = set(_available_audio_outputs())

    for fmt in INPUT_FORMATS:
        targets = set(mapping[fmt])
        # Every image the app writes stays reachable from every image it reads,
        # minus the self-pairing - and never a video or audio target, whose
        # converters refuse stills rather than emitting a one-frame clip or an
        # empty audio stream.
        assert image_outputs - {normalize_format(fmt)} <= targets, (
            f"{fmt} lost image targets: {sorted(targets)}"
        )
        assert audio_outputs.isdisjoint(targets), (
            f"{fmt} must not offer audio extraction: {sorted(targets)}"
        )
        if fmt == "gif" and video_available():
            # The one exception to "no video from a still": a GIF *is* an
            # animation, and the video converter reads it (gif -> any video),
            # so its row offers every video container alongside the image
            # targets. It still has no audio stream, so MP3/WAV stay off it.
            assert video_outputs <= targets, (
                f"gif lost video targets: {sorted(targets)}"
            )
        else:
            assert video_outputs.isdisjoint(targets), (
                f"{fmt} must not offer a video target from a still image: "
                f"{sorted(targets)}"
            )

    if video_available() or audio_outputs:
        for fmt in VIDEO_INPUT_FORMATS:
            targets = set(mapping[fmt])
            if video_available():
                # Every video container except the one it already is (and
                # every still frame) is reachable from a clip.
                assert video_outputs - {normalize_format(fmt)} <= targets, (
                    f"{fmt} lost video targets: {sorted(targets)}"
                )
                assert image_outputs <= targets, (
                    f"{fmt} lost frame-extraction targets: {sorted(targets)}"
                )
            if audio_outputs:
                # A clip has an audio stream: MP3/WAV are always offered.
                assert audio_outputs <= targets, (
                    f"{fmt} lost audio-extraction targets: {sorted(targets)}"
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
    video_outputs = _available_video_outputs()
    audio_outputs = _available_audio_outputs()
    outputs = [*OUTPUT_FORMATS, *video_outputs, *audio_outputs]

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
        gif_targets = [
            out for out in OUTPUT_FORMATS if out != "gif"
        ] + video_outputs
        expected = next(out for out in preference if out in gif_targets)
        assert expected == "mp4", (
            f"a gif input would preselect '{expected}' although MP4 is available"
        )

        # A non-MP4 video row must land on MP4. Every other target for a clip
        # is a still-frame extraction or an audio extraction, so preselecting
        # one would silently hand the user the wrong kind of file. An .mp4 row
        # is the mirror image: MP4 is its own format, so it must land on the
        # next video container rather than looping back to itself or falling
        # through to a frame.
        for fmt in VIDEO_INPUT_FORMATS:
            targets = [out for out in OUTPUT_FORMATS if out != normalize_format(fmt)]
            targets += [out for out in video_outputs if out != normalize_format(fmt)]
            targets += audio_outputs
            expected = next(out for out in preference if out in targets)
            if fmt == "mp4":
                assert expected in video_outputs, (
                    f"an .mp4 input would preselect '{expected}', which is "
                    "not a video-conversion target"
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
    -> any video reads it as an animation, a video -> gif writes one), so
    the second ring is not just "the video outputs". Audio extraction writes
    its own kind, so MP3/WAV get a third ring rather than sharing the video
    one.
    """
    rings = _js_format_rings()
    backend = FluxAPI().registry.supported_output_rings
    video_outputs = _available_video_outputs()
    audio_outputs = _available_audio_outputs()

    # The mock is a static literal: entries whose converter is capability-
    # gated away are tolerated the same way a stale AVIF input is.
    if not _avif_available():
        rings["image"] = [fmt for fmt in rings["image"] if fmt != "avif"]
    if not _heif_available():
        rings["image"] = [fmt for fmt in rings["image"] if fmt != "heic"]
    rings["video"] = [fmt for fmt in rings.get("video", []) if fmt in video_outputs or fmt == "gif"]
    rings["audio"] = [fmt for fmt in rings.get("audio", []) if fmt in audio_outputs]

    expected_kinds = {"image", "video"}
    if audio_outputs:
        expected_kinds.add("audio")
    if not video_outputs:
        rings["video"] = []
    if not audio_outputs:
        rings.pop("audio", None)

    assert set(rings) == expected_kinds, f"unexpected rings: {sorted(rings)}"
    assert sorted(rings["image"]) == sorted(backend["image"]), (
        f"mock image ring {sorted(rings['image'])} != backend {sorted(backend['image'])}"
    )
    assert sorted(rings.get("video", [])) == sorted(backend.get("video", [])), (
        f"mock video ring {sorted(rings.get('video', []))} != "
        f"backend {sorted(backend.get('video', []))}"
    )
    if audio_outputs:
        assert sorted(rings["audio"]) == sorted(backend["audio"]), (
            f"mock audio ring {sorted(rings['audio'])} != "
            f"backend {sorted(backend['audio'])}"
        )

    every_output = set()
    for formats in backend.values():
        every_output |= set(formats)
    assert every_output == set(FluxAPI().getSupportedFormats()["output"]), (
        "the rings together must cover every format the backend can write"
    )
    if video_outputs:
        # The whole reason rings exist: GIF belongs to both, video-only
        # formats to the video ring alone.
        assert "gif" in rings["image"] and "gif" in rings["video"]
        assert video_outputs and set(video_outputs) <= set(rings["video"])
        assert set(video_outputs).isdisjoint(rings["image"])
    else:
        assert rings["video"] == []
    if audio_outputs:
        assert set(audio_outputs) <= set(rings["audio"])
        assert set(audio_outputs).isdisjoint(rings["image"])
        assert set(audio_outputs).isdisjoint(rings["video"])
    else:
        assert "audio" not in rings


def test_get_supported_formats_carries_the_ring_grouping() -> None:
    """window.py ships the rings on the same payload as kinds and targets.

    The donut cannot group what it never receives: without this key
    FormatDonut falls back to kinds, which has no idea GIF is also a video
    conversion or that MP3/WAV are a third ring - so the payload key itself
    is pinned, not just its source.
    """
    payload = FluxAPI().getSupportedFormats()
    video_outputs = _available_video_outputs()
    audio_outputs = _available_audio_outputs()

    assert "rings" in payload, "getSupportedFormats() does not carry rings"
    rings = payload["rings"]
    assert rings == FluxAPI().registry.supported_output_rings

    every_output = set()
    for formats in rings.values():
        every_output |= set(formats)
    assert every_output == set(payload["output"])

    if video_outputs:
        assert "gif" in rings["image"] and "gif" in rings["video"]
        assert set(video_outputs) <= set(rings["video"])
        assert set(video_outputs).isdisjoint(rings["image"])
    else:
        assert rings["video"] == []

    if audio_outputs:
        assert set(audio_outputs) <= set(rings["audio"])
        assert set(audio_outputs).isdisjoint(rings["image"])
        assert set(audio_outputs).isdisjoint(rings["video"])
    else:
        assert "audio" not in rings


def test_mock_matrix_offers_video_targets_for_gif_inputs() -> None:
    """The mock's matrix builder gives GIF's row every video target.

    The backend side of this is pinned by test_conversion_matrix (the gif
    input row contains every video output); this pins the mock's computed
    copy, which is built by hand in useFlux.js rather than derived. Without
    the line, the two matrices disagree for exactly one input and gif ->
    video silently exists only where the registry does.
    """
    source = USE_FLUX.read_text(encoding="utf-8")
    assert "takesVideo = isVideo || input === 'gif'" in source, (
        "the mock's targets builder no longer offers video targets for gif inputs"
    )
    assert "takesAudio = isVideo" in source, (
        "the mock's targets builder offers audio extraction for a gif, "
        "which has no audio stream"
    )

    mapping = FluxAPI().registry.supported_targets_by_input
    video_outputs = _available_video_outputs()
    audio_outputs = _available_audio_outputs()
    if video_available():
        assert set(video_outputs) <= set(mapping["gif"]), (
            "the backend gif row must offer every video target"
        )
    else:
        assert set(video_outputs).isdisjoint(mapping["gif"])
    assert set(audio_outputs).isdisjoint(mapping["gif"]), (
        "a gif has no audio stream and must never offer MP3/WAV"
    )
