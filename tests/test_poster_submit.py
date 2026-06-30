import asyncio

from ghost_protocol.poster import GhostPoster


class _FakeControl:
    def __init__(self, label: str, y: float):
        self.label = label
        self.y = y
        self.clicked = False

    async def is_visible(self, timeout=None):
        return True

    async def inner_text(self, timeout=None):
        return self.label

    async def get_attribute(self, name, timeout=None):
        return None

    async def bounding_box(self, timeout=None):
        return {"x": 10, "y": self.y, "width": 100, "height": 40}

    async def scroll_into_view_if_needed(self, timeout=None):
        return None

    async def click(self, timeout=None):
        self.clicked = True


class _FakeCommentInput:
    def __init__(self, y: float, height: float = 100):
        self.y = y
        self.height = height

    async def bounding_box(self, timeout=None):
        return {"x": 300, "y": self.y, "width": 900, "height": self.height}

    async def evaluate(self, script):
        return False


class _FakeLocator:
    def __init__(self, controls):
        self.controls = controls

    async def count(self):
        return len(self.controls)

    def nth(self, index):
        return self.controls[index]


class _FakePage:
    def __init__(self, controls):
        self.controls = controls

    def locator(self, selector):
        return _FakeLocator(self.controls)

    async def evaluate(self, script):
        return False


def test_post_submit_ignores_attachment_register_button():
    attachment = _FakeControl("등록(50회)", y=400)
    final_submit = _FakeControl("등록", y=520)
    cancel = _FakeControl("취소", y=520)

    poster = GhostPoster()
    poster._page = _FakePage([attachment, final_submit, cancel])

    assert asyncio.run(poster._click_post_submit()) is True
    assert final_submit.clicked is True
    assert attachment.clicked is False
    assert cancel.clicked is False


def test_comment_submit_uses_plain_register_nearest_textarea():
    unrelated = _FakeControl("등록", y=120)
    register = _FakeControl("등록", y=430)
    recommend = _FakeControl("등록+추천", y=430)
    write = _FakeControl("글쓰기", y=500)

    poster = GhostPoster()
    poster._page = _FakePage([unrelated, register, recommend, write])
    comment_input = _FakeCommentInput(y=300, height=110)

    assert asyncio.run(poster._click_comment_submit(comment_input)) is True
    assert register.clicked is True
    assert unrelated.clicked is False
    assert recommend.clicked is False
    assert write.clicked is False
