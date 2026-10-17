#!/usr/bin/env python3
"""Calendar API helper using gcalcli's pipx credentials."""

import json
import pickle
import sys


def calendar_service():
    from googleapiclient.discovery import build
    from gcalcli import auth, env

    credentials = None
    for path in env.data_file_paths("oauth"):
        if not path.exists():
            continue
        with path.open("rb") as stream:
            try:
                credentials = pickle.load(stream)
            except (pickle.UnpicklingError, EOFError):
                stream.seek(0)
                credentials = auth.creds_from_legacy_json(json.load(stream))
        break
    if credentials is None:
        raise RuntimeError("gcalcli credentials not found")

    auth.refresh_if_expired(credentials)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def delete_event(service, calendar_name, event_id):
    matches = []
    page_token = None
    while True:
        result = service.calendarList().list(pageToken=page_token).execute()
        matches.extend(
            item["id"] for item in result.get("items", [])
            if item.get("summary") == calendar_name
        )
        page_token = result.get("nextPageToken")
        if not page_token:
            break

    if len(matches) != 1:
        raise RuntimeError("Calendar name is missing or ambiguous")
    service.events().delete(calendarId=matches[0], eventId=event_id).execute()


def quick_add_event(service, text):
    result = service.calendarList().list(maxResults=250).execute()
    primary = [item for item in result.get("items", []) if item.get("primary")]
    if len(primary) != 1:
        raise RuntimeError("Primary calendar is missing or ambiguous")
    calendar = primary[0]
    event = service.events().quickAdd(calendarId=calendar["id"], text=text).execute()
    return {"calendar": calendar["summary"], "event": event}


def main(argv):
    try:
        service = calendar_service()
        if len(argv) == 4 and argv[1] == "delete":
            delete_event(service, argv[2], argv[3])
        elif len(argv) == 3 and argv[1] == "quick":
            print(json.dumps(quick_add_event(service, argv[2])))
        else:
            print(
                "usage: gcal_api.py delete CALENDAR EVENT_ID | quick TEXT",
                file=sys.stderr,
            )
            return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
