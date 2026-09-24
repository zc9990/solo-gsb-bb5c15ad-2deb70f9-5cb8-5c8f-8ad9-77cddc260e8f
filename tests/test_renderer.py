"""renderer 核心逻辑测试(仅依赖标准库):python3 -m unittest discover -s tests"""

import unittest

from app.renderer import (
    PEDAL_ALREADY_DOWN,
    PEDAL_ALREADY_UP,
    UNPAIRED_NOTE_OFF,
    render,
)


def ev(time_ms, channel, kind, pitch=None):
    return {
        "time_ms": time_ms,
        "channel": channel,
        "type": kind,
        "pitch": pitch,
    }


class RenderTests(unittest.TestCase):
    def test_basic_on_off(self):
        result = render(
            1000,
            [ev(0, 0, "note_on", 60), ev(500, 0, "note_off", 60)],
        )
        self.assertEqual(
            result["intervals"],
            [{"channel": 0, "pitch": 60, "start_ms": 0, "end_ms": 500}],
        )
        self.assertEqual(result["errors"], [])

    def test_end_ms_closes_open_notes(self):
        result = render(200, [ev(10, 3, "note_on", 72)])
        self.assertEqual(
            result["intervals"],
            [{"channel": 3, "pitch": 72, "start_ms": 10, "end_ms": 200}],
        )

    def test_unpaired_note_off(self):
        result = render(
            100,
            [ev(0, 0, "note_on", 60), ev(10, 0, "note_off", 60), ev(20, 0, "note_off", 60)],
        )
        self.assertEqual(
            result["errors"], [{"index": 2, "reason": UNPAIRED_NOTE_OFF}]
        )

    def test_repeated_keys_get_independent_intervals_fifo(self):
        # 两次按键:0ms / 100ms;两次松键:200ms / 300ms,FIFO 配对
        result = render(
            1000,
            [
                ev(0, 0, "note_on", 60),
                ev(100, 0, "note_on", 60),
                ev(200, 0, "note_off", 60),
                ev(300, 0, "note_off", 60),
            ],
        )
        self.assertEqual(
            result["intervals"],
            [
                {"channel": 0, "pitch": 60, "start_ms": 0, "end_ms": 200},
                {"channel": 0, "pitch": 60, "start_ms": 100, "end_ms": 300},
            ],
        )

    def test_pedal_defers_release_and_cuts_all_together(self):
        result = render(
            1000,
            [
                ev(0, 0, "note_on", 60),
                ev(50, 0, "note_on", 64),
                ev(100, 0, "pedal_down"),
                ev(200, 0, "note_off", 60),   # 待释放
                ev(250, 0, "note_off", 64),   # 待释放
                ev(400, 0, "pedal_up"),       # 两个音同时截断于 400
            ],
        )
        self.assertEqual(
            result["intervals"],
            [
                {"channel": 0, "pitch": 60, "start_ms": 0, "end_ms": 400},
                {"channel": 0, "pitch": 64, "start_ms": 50, "end_ms": 400},
            ],
        )
        self.assertEqual(result["errors"], [])

    def test_reon_while_pedal_held_is_independent(self):
        # 踩着踏板时松键再重按:旧音等抬踏板截断,新音独立
        result = render(
            1000,
            [
                ev(0, 0, "note_on", 60),
                ev(50, 0, "pedal_down"),
                ev(100, 0, "note_off", 60),  # 旧音 -> 待释放
                ev(200, 0, "note_on", 60),   # 新音,独立区间
                ev(300, 0, "note_off", 60),  # 配对新音;踏板仍踩着 -> 也待释放
                ev(500, 0, "pedal_up"),      # 两音同时截断于 500
            ],
        )
        self.assertEqual(
            result["intervals"],
            [
                {"channel": 0, "pitch": 60, "start_ms": 0, "end_ms": 500},
                {"channel": 0, "pitch": 60, "start_ms": 200, "end_ms": 500},
            ],
        )

    def test_note_off_while_pedal_down_consumes_from_held_fifo(self):
        result = render(
            1000,
            [
                ev(0, 0, "note_on", 60),
                ev(10, 0, "note_on", 60),
                ev(20, 0, "pedal_down"),
                ev(30, 0, "note_off", 60),  # 配对最早按住的那个
                ev(40, 0, "pedal_up"),      # 截断待释放的旧音
                # 第二次按下的音仍按住,到 end_ms 才结束
            ],
        )
        self.assertEqual(
            result["intervals"],
            [
                {"channel": 0, "pitch": 60, "start_ms": 0, "end_ms": 40},
                {"channel": 0, "pitch": 60, "start_ms": 10, "end_ms": 1000},
            ],
        )

    def test_invalid_pedal_switches(self):
        result = render(
            1000,
            [
                ev(0, 0, "pedal_down"),
                ev(10, 0, "pedal_down"),  # 重复踩
                ev(20, 0, "pedal_up"),
                ev(30, 0, "pedal_up"),    # 未踩时抬
            ],
        )
        self.assertEqual(
            result["errors"],
            [
                {"index": 1, "reason": PEDAL_ALREADY_DOWN},
                {"index": 3, "reason": PEDAL_ALREADY_UP},
            ],
        )

    def test_channels_are_independent(self):
        result = render(
            1000,
            [
                ev(0, 0, "pedal_down"),
                ev(0, 1, "note_on", 60),   # 通道1没踩踏板
                ev(10, 1, "note_off", 60),  # 立即截断
                ev(20, 0, "note_on", 70),   # 通道0踩着踏板
                ev(30, 0, "note_off", 70),  # 待释放,到 end_ms 才截断
            ],
        )
        self.assertEqual(
            result["intervals"],
            [
                {"channel": 1, "pitch": 60, "start_ms": 0, "end_ms": 10},
                {"channel": 0, "pitch": 70, "start_ms": 20, "end_ms": 1000},
            ],
        )
        self.assertEqual(result["errors"], [])

    def test_same_timestamp_input_order_is_kept(self):
        # 同一时刻:先抬踏板截断待释放音,再按下新音
        result = render(
            1000,
            [
                ev(0, 0, "note_on", 60),
                ev(5, 0, "pedal_down"),
                ev(10, 0, "note_off", 60),
                ev(20, 0, "pedal_up"),
                ev(20, 0, "note_on", 60),  # 同时刻,按输入顺序新起一个音
            ],
        )
        self.assertEqual(
            result["intervals"],
            [
                {"channel": 0, "pitch": 60, "start_ms": 0, "end_ms": 20},
                {"channel": 0, "pitch": 60, "start_ms": 20, "end_ms": 1000},
            ],
        )

    def test_empty_events(self):
        result = render(0, [])
        self.assertEqual(result, {"intervals": [], "errors": []})

    def test_zero_length_interval(self):
        result = render(
            100,
            [ev(10, 0, "note_on", 60), ev(10, 0, "note_off", 60)],
        )
        self.assertEqual(
            result["intervals"],
            [{"channel": 0, "pitch": 60, "start_ms": 10, "end_ms": 10}],
        )

    def test_unpaired_note_off_while_pedal_held(self):
        # 踏板踩着也不能凭空配对松键
        result = render(
            100,
            [ev(0, 0, "pedal_down"), ev(10, 0, "note_off", 60)],
        )
        self.assertEqual(
            result["errors"], [{"index": 1, "reason": UNPAIRED_NOTE_OFF}]
        )


if __name__ == "__main__":
    unittest.main()
