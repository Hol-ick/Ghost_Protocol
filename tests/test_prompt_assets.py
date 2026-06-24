import json
from pathlib import Path
import unittest


PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def _load(name: str):
    return json.loads((PROMPTS / name).read_text(encoding="utf-8"))


class PromptAssetTest(unittest.TestCase):
    def test_persona_keys_have_tone_and_profile(self):
        personas = _load("personas.json")
        tones = _load("tones.json")
        profiles = _load("persona_profiles.json")

        persona_keys = {item["key"] for item in personas}
        self.assertEqual(persona_keys, set(tones))
        self.assertEqual(persona_keys, set(profiles))

    def test_profiles_define_behavioral_moves(self):
        profiles = _load("persona_profiles.json")
        for key, profile in profiles.items():
            with self.subTest(key=key):
                self.assertTrue(profile.get("good_moves"))
                self.assertTrue(profile.get("bad_moves"))
                self.assertTrue(profile.get("never_say"))

    def test_generation_prompt_rejects_generic_question_templates(self):
        prompt = (PROMPTS / "generate_post.txt").read_text(encoding="utf-8")
        for template in (
            "X 왜 자꾸 나옴",
            "X 언제까지",
            "X 진짜임",
            "X 기준이 뭐임",
            "X 이게 뭐냐",
        ):
            with self.subTest(template=template):
                self.assertIn(template, prompt)
        self.assertIn("기본 문형은 평서형", prompt)
        self.assertIn("질문을 평서형처럼 보이게", prompt)
        self.assertIn("질문형 제목은 반드시 `?`로 끝낸다", prompt)
        self.assertIn("판단 직전에 멈췄는가", prompt)
        self.assertIn("진위 확인이나 유행 감시를 하지 않는다", prompt)
        self.assertIn("갑자기 땡기네", prompt)
        self.assertIn("사용 맥락", prompt)
        self.assertIn("조건절이나 미완성 연결", prompt)
        self.assertIn("입력에 없는 1인칭 경험", prompt)
        self.assertIn("욕설·비하어·성적 농담·외모 품평", prompt)
        self.assertIn("무대, 카메라, 조명, 편집", prompt)
        self.assertIn("같은 안전어로 끝나는 글", prompt)
        self.assertIn("무명자는 아직 묶여있을 카드임", prompt)
        self.assertIn("질문형이 추천 요청·룰 확인·가격 확인이 아닌가", prompt)
        self.assertIn("이름 왜 익숙함", prompt)

    def test_generation_prompt_requires_concrete_complete_judgment(self):
        prompt = (PROMPTS / "generate_post.txt").read_text(encoding="utf-8")
        self.assertIn("핵심 대상을 `이거`, `그거`", prompt)
        self.assertIn("본문은 그 판단의 이유·결과·비용·비교 근거", prompt)
        self.assertIn("입력에 과거 사례와 현재 사례가 모두 있을 때", prompt)

    def test_comment_prompt_avoids_newbie_meaning_questions(self):
        prompt = (PROMPTS / "generate_comment.txt").read_text(encoding="utf-8")
        self.assertNotIn("맥락 질문", prompt)
        self.assertIn("무슨 뜻임?", prompt)
        self.assertIn("사용 맥락이 뭐임?", prompt)
        self.assertIn("뜻풀이 질문", prompt)
        self.assertIn("빈 배열보다 1개 짧은 댓글을 우선", prompt)
        self.assertIn("댓글 1개를 기본값", prompt)
        self.assertIn("$shared_writing_contract", prompt)
        self.assertIn("동조는 기본값이 아니다", prompt)
        self.assertIn("작은 독립 정보나 각도", prompt)
        self.assertIn("완충어만 남기는 댓글은 실패", prompt)
        self.assertIn("구체 조건을 하나 붙이거나 삭제", prompt)

    def test_generation_prompt_prefers_aligned_target_comments(self):
        prompt = (PROMPTS / "generate_post.txt").read_text(encoding="utf-8")
        self.assertIn("target_comments를 비우지 말고 1개를 우선", prompt)
        self.assertIn("같은 게임명·카드·룰·가격·숫자·장면", prompt)
        self.assertIn("최대 2개까지", prompt)
        self.assertIn("$shared_writing_contract", prompt)

    def test_shared_writing_contract_is_used_by_post_and_comment_prompts(self):
        shared = (PROMPTS / "shared_writing_contract.txt").read_text(encoding="utf-8")
        post_prompt = (PROMPTS / "generate_post.txt").read_text(encoding="utf-8")
        comment_prompt = (PROMPTS / "generate_comment.txt").read_text(encoding="utf-8")

        self.assertIn("게시글과 댓글은 같은 대화 세계", shared)
        self.assertIn("기본 동작은 공감이 아니다", shared)
        self.assertIn("질문은 예외 동작", shared)
        self.assertIn("입력에 없는 기억·경험·체험", shared)
        self.assertIn("$shared_writing_contract", post_prompt)
        self.assertIn("$shared_writing_contract", comment_prompt)

    def test_humblebragger_does_not_invent_prior_experience(self):
        profiles = _load("persona_profiles.json")
        profile = profiles["humblebragger"]
        self.assertIn("기억을 지어내지 않고", profile["vocab_style"])
        self.assertIn("전에 본 거 같은데", profile["never_say"])


if __name__ == "__main__":
    unittest.main()
