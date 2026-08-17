import unittest
from gst_profile.tracerlog import parse_line, ParseStats, Record, CapsEvent, parse_wall_ns

EL = "0:00:00.041343812 2724071 0x7b934c000d20 TRACE             GST_TRACER :0:: element-latency, element-id=(string)0x5783585dbb30, element=(string)capsfilter0, src=(string)src, time=(guint64)330559, ts=(guint64)41203431;"
BUF = "0:00:00.040898155 2724071 0x7b934c000d20 TRACE             GST_TRACER :0:: buffer, thread-id=(guint64)135872565480736, ts=(guint64)40872872, pad-ix=(uint)1, element-ix=(uint)0, peer-pad-ix=(uint)0, peer-element-ix=(uint)5, buffer-size=(uint)614400, have-buffer-pts=(boolean)1, buffer-pts=(guint64)0, have-buffer-dts=(boolean)0, buffer-dts=(guint64)18446744073709551615, have-buffer-duration=(boolean)1, buffer-duration=(guint64)33333333, buffer-flags=(GstBufferFlags)0;"
MSG = '0:00:00.025577725 2724071 0x5783585a89b0 TRACE             GST_TRACER :0:: message, thread-id=(guint64)96221634660784, ts=(guint64)25553839, element-ix=(uint)0, name=(string)structure-change, structure=(structure)"GstMessageStructureChange\\,\\ type\\=\\(GstStructureChangeType\\)link\\;";'
FMT = "0:00:00.015153929 2724071 0x5783585a89b0 DEBUG             GST_TRACER gsttracerrecord.c:123:gst_tracer_record_build_format: new format string: buffer, thread-id=(guint64)%lu;"
NOISE = "0:00:00.011331951 2724528 0x5e2317d4ea30 DEBUG             GST_TRACER gsttracer.c:159:gst_tracer_register:<registry0> update existing feature 0x5e2317c54bb0 (latency)"
CAPS = '0:00:00.017852044 2724438 0x761d8c000d50 DEBUG              GST_EVENT gstpad.c:5892:gst_pad_send_event_unchecked:<capsfilter0:sink> have event type caps event: 0x761d8800cc00, time 99:99:99.999999999, seq-num 34, GstEventCaps, caps=(GstCaps)"video/x-raw\\,\\ format\\=\\(string\\)NV12\\,\\ width\\=\\(int\\)320\\,\\ height\\=\\(int\\)240\\,\\ framerate\\=\\(fraction\\)30/1";'


class TracerLogTest(unittest.TestCase):
    def test_element_latency_record(self):
        r = parse_line(EL)
        self.assertIsInstance(r, Record)
        self.assertEqual(r.kind, "element-latency")
        self.assertEqual(r.fields["element"], "capsfilter0")
        self.assertEqual(r.fields["time"], 330559)
        self.assertEqual(r.fields["ts"], 41203431)
        self.assertEqual(r.wall_ns, 41343812)
        self.assertEqual(r.thread, "0x7b934c000d20")

    def test_buffer_record_types(self):
        r = parse_line(BUF)
        self.assertEqual(r.fields["buffer-size"], 614400)
        self.assertIs(r.fields["have-buffer-pts"], True)
        self.assertIs(r.fields["have-buffer-dts"], False)
        self.assertEqual(r.fields["peer-element-ix"], 5)

    def test_structure_field_unescaped(self):
        r = parse_line(MSG)
        self.assertEqual(r.kind, "message")
        self.assertEqual(r.fields["name"], "structure-change")
        self.assertTrue(r.fields["structure"].startswith("GstMessageStructureChange, type=(GstStructureChangeType)link;"))

    def test_format_declaration_and_noise_ignored(self):
        st = ParseStats()
        self.assertIsNone(parse_line(FMT, st))
        self.assertIsNone(parse_line(NOISE, st))
        self.assertIsNone(parse_line("garbage line", st))
        self.assertEqual((st.lines, st.format_decls, st.unparsed, st.records), (3, 1, 1, 0))

    def test_caps_event(self):
        c = parse_line(CAPS)
        self.assertIsInstance(c, CapsEvent)
        self.assertEqual(c.pad, "capsfilter0:sink")
        self.assertEqual(c.caps, "video/x-raw, format=(string)NV12, width=(int)320, height=(int)240, framerate=(fraction)30/1")

    def test_wall_ns(self):
        self.assertEqual(parse_wall_ns("0:00:01.500000000"), 1_500_000_000)
        self.assertEqual(parse_wall_ns("1:02:03.000000001"), (3600 + 120 + 3) * 10**9 + 1)


if __name__ == "__main__":
    unittest.main()
