import copy
import unittest

from gst_profile.redact import redact_session, redact_text, REDACTED


def session(**over):
    d = {
        "schema": "gst-profile/1",
        "session": {"id": "s1", "mode": "run",
                    "launch": 'rtspsrc location=rtsp://admin:hunter2@10.0.0.9/cam1 ! fakesink',
                    "command": None, "notes": ["lines read 10, dropped 0"]},
        "graph": {"elements": [{"id": "rtspsrc0", "props": {"location": "rtsp://a:b@h/c", "latency": "200"}}],
                  "links": []},
        "events": [{"t": 1.0, "kind": "note", "text": "opened rtsp://user:pw@cam.local/1"}],
        "findings": [{"id": "F-1", "why": "src rtsp://x:y@h stalls", "fix_text": "check the camera", "title": "t"}],
        "series": {"t": []},
    }
    d.update(over)
    return d


class RedactText(unittest.TestCase):
    def test_credentials_in_urls_are_stripped(self):
        self.assertEqual(redact_text("rtsp://admin:hunter2@10.0.0.9/cam"), f"rtsp://{REDACTED}@10.0.0.9/cam")

    def test_location_values_are_stripped_even_unquoted(self):
        self.assertEqual(redact_text("filesrc location=/home/user/secret.mp4 ! decodebin"),
                         f"filesrc location={REDACTED} ! decodebin")

    def test_token_looking_strings_are_stripped(self):
        out = redact_text("auth eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc done")
        self.assertIn(REDACTED, out)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc", out)

    def test_plain_pipeline_text_is_untouched(self):
        s = "videotestsrc is-live=true ! videoconvert ! queue ! fakesink sync=false"
        self.assertEqual(redact_text(s), s)


class RedactSession(unittest.TestCase):
    def test_launch_props_events_findings_are_redacted(self):
        d = redact_session(session())
        self.assertNotIn("hunter2", d["session"]["launch"])
        self.assertEqual(d["graph"]["elements"][0]["props"]["location"], REDACTED)
        self.assertEqual(d["graph"]["elements"][0]["props"]["latency"], "200")
        self.assertNotIn("user:pw", d["events"][0]["text"])
        self.assertNotIn("x:y", d["findings"][0]["why"])

    def test_the_original_session_is_not_mutated(self):
        src = session()
        before = copy.deepcopy(src)
        redact_session(src)
        self.assertEqual(src, before)

    def test_wrap_command_is_redacted(self):
        d = redact_session(session(session={"id": "s", "mode": "wrap", "launch": None,
                                            "command": ["./app", "--url", "http://u:p@h/x"], "notes": []}))
        self.assertNotIn("u:p", d["session"]["command"][2])


if __name__ == "__main__":
    unittest.main()
