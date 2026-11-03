# Real release desktop recording — first-stage preflight

This independent workflow only runs on `film-capture/**` branches or explicit dispatch. It has read-only repository permissions, does not rebuild/re-publish applications, does not modify production files and does not cancel other work.

It downloads the actual public release AppImage/EXE and records their native desktop using X11/gdigrab. The Linux GUI exposes a read-only visible-widget tree for external mouse automation; the released application is not modified. Windows uses external Win32 UI automation against the released EXE, not DrawToBitmap or a recompiled UI harness.

The first stage tests launch, page navigation and real video capture; Windows also checks single-instance behavior. These checks are **not** a claim that downloads, browser integration, video/DVR and P2P have passed. Those require subsequent functional scenarios and are explicitly NOT_RUN in this stage.

On Linux, the existing source unit suite runs independently and is labelled source-only. A source checkout is not assumed to equal the published binary.

Windows settings are preseeded with Turkish language, clipboard capture off, and warmup off to keep the initial isolated navigation recording deterministic. Functional tests must explicitly test enabled capture and engine setup later.

Artifacts contain original MP4, actual desktop PNGs, visible control metadata, release asset IDs/SHA256 and a report. Blank/locked desktops, missing native windows, failed navigation or a broken recording fail the preflight; they are never replaced with synthetic videos.
