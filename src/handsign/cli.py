"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def _cmd_run(args: argparse.Namespace) -> int:
    from .config import ConfigError, load_config
    from .engine import Engine

    try:
        cfg = load_config(args.config)
    except ConfigError as err:
        print(f"handsign: config error: {err}", file=sys.stderr)
        return 2
    try:
        engine = Engine(cfg, preview=args.preview, record=args.record, dry_run=args.dry_run)
    except RuntimeError as err:
        print(f"handsign: {err}", file=sys.stderr)
        return 1
    try:
        return engine.run()
    except RuntimeError as err:
        print(f"handsign: {err}", file=sys.stderr)
        return 1


def _cmd_init(args: argparse.Namespace) -> int:
    from .config import default_config_path, default_config_text

    path = args.config or default_config_path()
    if path.exists() and not args.force:
        print(f"{path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(), encoding="utf-8")
    print(f"wrote {path}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    from .config import ConfigError, load_config

    try:
        cfg = load_config(args.config)
    except ConfigError as err:
        print(f"config error: {err}", file=sys.stderr)
        return 2
    for b in cfg.bindings:
        hand = f" [{b.hand}]" if b.hand else ""
        print(f"{b.gesture}{hand} -> {b.action.describe()}")
    return 0


def _cmd_ctl(args: argparse.Namespace) -> int:
    from .control import send

    try:
        reply = send(args.command)
    except OSError:
        print("handsign is not running", file=sys.stderr)
        return 1
    print(json.dumps(reply))
    return 0 if reply.get("ok") else 1


def _cmd_service(args: argparse.Namespace) -> int:
    from .service import ServiceError, get_service

    status = 0
    try:
        service = get_service()
        if args.action == "install":
            service.install(start=not args.no_start, force=args.force)
        elif args.action in ("status", "logs"):
            status = getattr(service, args.action)()
        else:
            getattr(service, args.action)()
    except ServiceError as err:
        print(f"handsign: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # leaving `logs`
        return 0
    if args.action == "status":
        from .control import send

        try:
            print(f"daemon: {json.dumps(send('status'))}")
        except OSError:
            print("daemon: not reachable")
    return status


def _cmd_detect(args: argparse.Namespace) -> int:
    import cv2

    from .config import load_config
    from .landmarks import HandTracker
    from .poses import classify

    cfg = load_config(args.config)
    status = 0
    with HandTracker(max_hands=2, min_confidence=0.3, mirrored=False, video=False) as tracker:
        for path in args.images:
            image = cv2.imread(str(path))
            if image is None:
                print(f"{path}: cannot read image", file=sys.stderr)
                status = 1
                continue
            hands = tracker.detect(image)
            if not hands:
                print(f"{path}: no hand")
            for hand in hands:
                pose = classify(hand, cfg.recognition.thresholds)
                fingers = "".join(c if on else "-" for c, on in zip("TIMRP", pose.fingers))
                print(f"{path}: {hand.handedness} {pose.name} {pose.confidence:.2f} [{fingers}]")
    return status


def _cmd_cameras(args: argparse.Namespace) -> int:
    from .camera import list_cameras

    cameras = list_cameras()
    for index, width, height in cameras:
        print(f"{index}: {width}x{height}")
    return 0 if cameras else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="handsign", description="Control the computer with hand signs."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("-c", "--config", type=Path, help="config file (default: user config)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="start recognising gestures")
    run.add_argument("--preview", action="store_true", help="show a debug window")
    run.add_argument("--dry-run", action="store_true", help="recognise but run no actions")
    run.add_argument("--record", type=Path, metavar="FILE", help="dump landmarks as JSON lines")
    run.set_defaults(func=_cmd_run)

    init = sub.add_parser("init", help="write the default config file")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=_cmd_init)

    sub.add_parser("check", help="validate the config and list bindings").set_defaults(
        func=_cmd_check
    )

    ctl = sub.add_parser("ctl", help="talk to the running daemon")
    ctl.add_argument("command", choices=["status", "pause", "resume", "toggle", "quit"])
    ctl.set_defaults(func=_cmd_ctl)

    service = sub.add_parser(
        "service", help="run handsign in the background (systemd on Linux, launchd on macOS)"
    )
    service.add_argument(
        "action", choices=["install", "uninstall", "start", "stop", "restart", "status", "logs"]
    )
    service.add_argument("--no-start", action="store_true", help="install: only enable at login")
    service.add_argument(
        "--force", action="store_true", help="install on macOS: rebuild Handsign.app"
    )
    service.set_defaults(func=_cmd_service)

    detect = sub.add_parser("detect", help="classify hands in still images")
    detect.add_argument("images", nargs="+", type=Path)
    detect.set_defaults(func=_cmd_detect)

    sub.add_parser("cameras", help="list usable cameras").set_defaults(func=_cmd_cameras)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.verbose:
        logging.getLogger("handsign").setLevel(logging.DEBUG)
    # Quieten TensorFlow Lite / glog chatter from MediaPipe.
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    return args.func(args)
