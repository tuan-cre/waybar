import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import gcal_tui
import gcal_api


class CalendarDataTests(unittest.TestCase):
    def test_fetch_includes_month_end_and_preserves_ids(self):
        tsv = (
            "id\tcalendar\tstart_date\tstart_time\tend_date\tend_time\ttitle\n"
            "timed\tWork\t2026-02-28\t00:00\t2026-02-28\t01:00\tMidnight\n"
            "all-day\tHome\t2026-02-10\t\t2026-02-11\t\tHoliday\n"
            "multi\tWork\t2026-01-30\t\t2026-02-03\t\tMulti-day\n"
        )
        with patch.object(gcal_tui.subprocess, "run",
                          return_value=subprocess.CompletedProcess([], 0, tsv, "")) as run:
            events = gcal_tui.fetch_events(2026, 2)

        self.assertEqual(run.call_args.args[0][-2:], ["2026-02-01", "2026-03-01"])
        self.assertEqual(events[28], [("timed", "Work", "00:00", "Midnight", False)])
        self.assertEqual(events[10], [("all-day", "Home", "", "Holiday", True)])
        self.assertEqual(events[1], [("multi", "Work", "", "Multi-day", True)])
        self.assertNotIn(3, events)

    def test_cache_discards_invalid_event_values(self):
        self.assertIsNone(gcal_tui.normalize_event(["id", None, "Title", False]))
        self.assertIsNone(gcal_tui.normalize_event(["id", "", "Title", 0]))
        self.assertEqual(
            gcal_tui.normalize_event(["id", "Work", "", "Title", True]),
            ("id", "Work", "", "Title", True),
        )

    def test_created_event_items_keep_real_id_and_span_days(self):
        payload = {
            "calendar": "Work",
            "event": {
                "id": "created-id",
                "summary": "Trip",
                "start": {"date": "2026-04-30"},
                "end": {"date": "2026-05-02"},
            },
        }
        items = gcal_tui._created_event_items(payload)
        self.assertEqual([item[:2] for item in items], [
            ((2026, 4), 30), ((2026, 5), 1),
        ])
        self.assertEqual(items[0][2], ("created-id", "Work", "", "Trip", True))

    def test_delete_uses_exact_id_and_refuses_ambiguous_calendar(self):
        class Request:
            def __init__(self):
                self.args = None

            def execute(self):
                return {"items": [{"id": "work-id", "summary": "Work"}]}

        class Service:
            def __init__(self):
                self.request = Request()

            def calendarList(self):
                return self

            def list(self, **_kwargs):
                return self.request

            def events(self):
                return self

            def delete(self, **kwargs):
                self.request.args = kwargs
                return self.request

        service = Service()
        gcal_api.delete_event(service, "Work", "selected-event-id")
        self.assertEqual(service.request.args, {
            "calendarId": "work-id", "eventId": "selected-event-id"
        })

        with patch.object(service, "list", return_value=Request()):
            service.list().execute = lambda: {
                "items": [{"id": "1", "summary": "Work"},
                          {"id": "2", "summary": "Work"}]
            }
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                gcal_api.delete_event(service, "Work", "selected-event-id")

    def test_quick_add_uses_primary_calendar_and_returns_event(self):
        class Request:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value

        class Service:
            def calendarList(self):
                return self

            def list(self, **_kwargs):
                return Request({"items": [
                    {"id": "work-id", "summary": "Work", "primary": True}
                ]})

            def events(self):
                return self

            def quickAdd(self, **kwargs):
                self.kwargs = kwargs
                return Request({"id": "new-id", "summary": "Meeting"})

        service = Service()
        result = gcal_api.quick_add_event(service, "Meeting tomorrow")
        self.assertEqual(service.kwargs, {
            "calendarId": "work-id", "text": "Meeting tomorrow"
        })
        self.assertEqual(result, {
            "calendar": "Work", "event": {"id": "new-id", "summary": "Meeting"}
        })

    def test_failed_fetch_does_not_cache_empty_month(self):
        events = {}
        ym = (2026, 2)
        with patch.object(gcal_tui, "fetch_events", return_value=None):
            gcal_tui.bg_fetch(events, *ym)

        self.assertNotIn(ym, events)
        self.assertIn(ym, gcal_tui._fetch_errors)
        gcal_tui._fetch_errors.discard(ym)

    def test_concurrent_fetches_preserve_all_months(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_file = gcal_tui.CACHE_FILE
            gcal_tui.CACHE_FILE = Path(directory) / "cache.json"
            try:
                cache = {}
                months = [(2026, month) for month in range(1, 9)]
                event_data = lambda _y, month: {
                    1: [(str(month), "", "event", False)]
                }
                with patch.object(gcal_tui, "fetch_events", side_effect=event_data):
                    threads = [threading.Thread(
                        target=gcal_tui.bg_fetch, args=(cache, *ym)
                    ) for ym in months]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
                self.assertEqual(set(cache), set(months))
                self.assertEqual(set(gcal_tui.load_cache()),
                                 {f"2026-{month:02d}" for month in range(1, 9)})
                self.assertEqual(list(Path(directory).glob("tmp*")), [])
            finally:
                gcal_tui.CACHE_FILE = cache_file


if __name__ == "__main__":
    unittest.main()
