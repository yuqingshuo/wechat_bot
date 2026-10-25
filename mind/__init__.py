# -*- coding: utf-8 -*-
"""
mind 包：把 5 个参考项目的能力融合进「微信小号恋爱关系」这一个主体。

借鉴来源与用途：
  - YuanYeYouTao/Yuki-QQbot          -> 身份 / 记忆 / 关系由自己持久化，换模型换账号都不丢
  - alpaim/ashley                    -> 情绪曲线、关系维度、里程碑、自我反思
  - Shikigami-Lab/Shikigami-Protocol -> 情绪 × 精力 × 好感 状态机、离线沉思、静默后主动
  - anrror/y-ai-accompany            -> OCEAN 动态人格、人格锚定(always/never)、口癖指纹、生命节律
  - Ameysr/Ai-Companion              -> 多层记忆（工作/短期/摘要/事实/经历）+ 一致性守卫

主体性约束（本包第一原则）：
  1. 所有状态都挂在「本机微信小号 × 某一个好友」这一对关系上，不是泛用 agent。
  2. 关系阶段（相识 → 相知 → 相恋）仍由 persona.json 的 affection 唯一决定，
     情绪 / 人格 / 记忆 / 内部状态只能「调味」——不许改阶段、不许改身份。
  3. 人格演化必须被 anchoring 锚定（名字、性别、年龄、身份、三观永不漂移）。
"""
import threading

from mind.store import MindStore
from mind import emotion as emotion_mod
from mind import memory as memory_mod
from mind import personality as personality_mod
from mind import state as state_mod
from mind import prompt as prompt_mod

__all__ = ["Mind", "get_mind", "reset_mind_cache", "emotion_mod", "memory_mod",
           "personality_mod", "state_mod", "prompt_mod", "MindStore"]

_mind_lock = threading.RLock()
_mind_instance = None


class Mind(object):
    """某个微信小号（本机登录的那个）的全部「内心」。

    一个 Mind 实例覆盖所有好友：每位好友拥有独立的情绪 / 关系 / 人格漂移 /
    内部状态 / 记忆银行，互不串味。
    """

    def __init__(self, base_dir=None):
        self.store = MindStore(base_dir)
        self.modules = {
            "emotion": emotion_mod,
            "memory": memory_mod,
            "personality": personality_mod,
            "state": state_mod,
            "prompt": prompt_mod,
        }

    # ---------------- 读取 ----------------

    def friend_state(self, user_id):
        """取某个好友的完整内心状态（缺失字段自动补全）。"""
        with self.store.state_lock:
            friends = self.store.state.setdefault("friends", {})
            fs = friends.get(user_id)
            if not isinstance(fs, dict):
                fs = {}
                friends[user_id] = fs
            return self._ensure_friend_state(fs)

    def _ensure_friend_state(self, fs):
        emo = fs.get("emotion")
        if not isinstance(emo, dict) or "valence" not in emo:
            fs["emotion"] = emotion_mod.default_emotion()
        rel = fs.get("relationship")
        if not isinstance(rel, dict) or "trust" not in rel:
            fs["relationship"] = emotion_mod.default_relationship()
        per = fs.get("personality")
        if not isinstance(per, dict) or "ocean" not in per:
            fs["personality"] = personality_mod.default_personality()
        st = fs.get("state")
        if not isinstance(st, dict) or "energy" not in st:
            fs["state"] = state_mod.default_state()
        for key, default_fn in (("anchoring", personality_mod.default_anchoring),
                                ("quirks", personality_mod.default_quirks)):
            if not isinstance(fs.get(key), dict) or not fs[key]:
                fs[key] = default_fn()
            else:
                for k, v in default_fn().items():
                    fs[key].setdefault(k, v)
        if not isinstance(fs.get("milestones"), list):
            fs["milestones"] = []
        if not isinstance(fs.get("thoughts"), list):
            fs["thoughts"] = []
        return fs

    def friend_bank(self, user_id):
        """取某个好友的记忆银行（多层记忆 L2~L5）。"""
        with self.store.bank_lock:
            friends = self.store.bank.setdefault("friends", {})
            bank = friends.get(user_id)
            if not isinstance(bank, dict):
                bank = {}
                friends[user_id] = bank
            memory_mod.ensure_bank(bank)
            return bank

    # ---------------- 持久化 ----------------

    def save_state(self, force=False):
        return self.store.save_state(force=force)

    def save_bank(self, force=False):
        return self.store.save_bank(force=force)

    def save_all(self, force=True):
        return self.store.save_all(force=force)

    # ---------------- 门面：事件 ----------------

    def on_friend_message(self, user_id, text, gap_minutes=None):
        """好友发来消息时更新内心状态，返回本次变化摘要（供日志与网页展示）。"""
        fs = self.friend_state(user_id)
        before = emotion_mod.emotion_label(fs["emotion"])
        fs["emotion"] = emotion_mod.emotion_after_message(
            fs["emotion"], text, from_friend=True, gap_minutes=gap_minutes)
        fs["relationship"] = emotion_mod.relationship_after_message(
            fs["relationship"], text, from_friend=True)
        fs["state"] = state_mod.state_after_message(fs["state"], text, from_friend=True)
        fs["state"] = state_mod.touch_active(fs["state"])
        if gap_minutes is not None:
            # 记下这次消息之前隔了多久：组装提示词时要靠它判断「别装作刚聊过」
            fs["state"]["last_gap_minutes"] = float(gap_minutes)
        after = emotion_mod.emotion_label(fs["emotion"])
        if before != after:
            fs["thoughts"] = state_mod.add_thought(
                fs["thoughts"], u"被对方那句话带动了情绪：%s" % after, kind="emotion")
        self.save_state()
        return {"emotion_before": before, "emotion_after": after,
                "energy": fs["state"].get("energy")}

    def on_bot_reply(self, user_id, text, sent_parts=1):
        """机器人发出回复后消耗精力，并更新「说完之后」的自我感受。"""
        fs = self.friend_state(user_id)
        fs["state"] = state_mod.state_after_reply(fs["state"], text, sent_parts=sent_parts)
        fs["emotion"] = emotion_mod.emotion_after_own_reply(fs["emotion"], text)
        self.save_state()
        return fs["state"].get("energy")

    def note_proactive(self, user_id, text, topic=""):
        """主动开口之后记一笔：写进时间线，同时刷新「当下念头」。

        主动搭话跟被动回消息不一样——是「我想找 TA 说话」这件事本身，
        所以既要在时间线上留痕，也要让下一句话知道自己刚主动找过人。
        """
        fs = self.friend_state(user_id)
        head = u"（%s）" % topic if topic else u""
        thought = u"刚刚主动找 TA 说了句%s%s" % (head, (text or u"")[:40])
        fs["thoughts"] = state_mod.add_thought(fs["thoughts"], thought, kind="intent")
        fs["state"]["intent"] = u"刚主动开口，在等 TA 回"
        self.save_state()
        return thought

    def record_milestone(self, user_id, key, text, importance=4):
        """登记一个关系里程碑（好感进阶 / 连续聊天 / 第一次晚安等）。"""
        fs = self.friend_state(user_id)
        for m in fs["milestones"]:
            if m.get("key") == key:
                return False
        fs["milestones"].append({"key": key, "text": text, "at": state_mod.now_ts()})
        if len(fs["milestones"]) > 60:
            del fs["milestones"][:-60]
        bank = self.friend_bank(user_id)
        memory_mod.add_episode(bank, text, kind="milestone", importance=importance)
        self.save_state()
        self.save_bank()
        return True

    def check_milestones(self, user_id, affection, stage_key):
        """按好感度 / 阶段 / 连续天数自动检测里程碑，返回本次新增的文本列表。"""
        fs = self.friend_state(user_id)
        rel = fs["relationship"]
        stage_name = emotion_mod.STAGE_CN.get(stage_key, u"相识")
        newly = []
        marks = ((1, u"第一次认真聊天", "affection_1"),
                 (30, u"好感度到 30，关系走进「相知」", "affection_30"),
                 (60, u"好感度过半", "affection_60"),
                 (80, u"好感度到 80，关系走进「相爱」", "affection_80"))
        for mark, text, key in marks:
            if affection >= mark and self.record_milestone(user_id, key, text):
                newly.append(text)
        for days, key, text in ((3, "streak_3", u"我们连着聊了 3 天"),
                                (7, "streak_7", u"我们连着聊了一整周"),
                                (30, "streak_30", u"我们连着聊了一个月")):
            if rel.get("streak_days", 0) >= days and self.record_milestone(user_id, key, text):
                newly.append(text)
        stage_text = u"关系阶段来到「%s」" % stage_name
        if self.record_milestone(user_id, "stage_%s" % stage_key, stage_text):
            newly.append(u"进入「%s」阶段" % stage_name)
        return newly

    def on_turn(self, user_id, incoming_text, reply_text, affection=0, stage_key="1",
                history=None, extractor=None):
        """一轮完整对话结束后的统一收尾：情绪 → 记忆 → 摘要滚动 → 里程碑。

        extractor: 可选 callable(messages, max_tokens) -> str，让 LLM 蒸馏记忆；
                   缺省时走纯规则抽取（不依赖网络，永远可用）。
        """
        fs = self.friend_state(user_id)
        bank = self.friend_bank(user_id)
        info = {"facts_added": 0, "episodes_added": 0, "summary_updated": False,
                "milestones": [], "archived": 0}

        fs["relationship"] = emotion_mod.relationship_tick(
            fs["relationship"], affection=affection, stage_key=stage_key,
            emotion=fs["emotion"])
        info["milestones"] = self.check_milestones(user_id, affection, stage_key)

        # 事实只从「对方说的话」里抽：长期记忆是关于这个人的，
        # 把自己说过的话当成对方的事实，下次复述出来会非常出戏。
        # 共同经历（约定、第一次…）才是双方都算的，所以用整段对话去检测。
        friend_text = incoming_text or ""
        combined = u"%s\n%s" % (friend_text, reply_text or "")
        for f in memory_mod.extract_facts(friend_text, extractor=extractor):
            if memory_mod.add_fact(bank, f["text"], importance=f.get("importance", 2),
                                   kind=f.get("kind", "fact"), source="chat"):
                info["facts_added"] += 1
        for e in memory_mod.detect_episodes(combined, affection=affection,
                                            stage_key=stage_key):
            if memory_mod.add_episode(bank, e["text"], kind=e.get("kind", "event"),
                                      importance=e.get("importance", 3)):
                info["episodes_added"] += 1

        if history:
            info["summary_updated"] = bool(
                memory_mod.rollup_summary(bank, history, extractor=extractor))
        info["archived"] = memory_mod.decay_and_archive(bank, affection=affection)
        self.save_state()
        self.save_bank()
        return info

    def reflect(self, user_id, affection=0, stage_key="1", extractor=None,
                idle_minutes=None, force=False):
        """后台沉思：空闲时生成一段内心独白，影响之后主动搭话的口气与话题。

        返回本次新增的独白文本（未产生则返回空串）。
        """
        fs = self.friend_state(user_id)
        bank = self.friend_bank(user_id)
        new_state, thought = state_mod.reflect(
            state=fs["state"], emotion=fs["emotion"], relationship=fs["relationship"],
            bank=bank, affection=affection, stage_key=stage_key, extractor=extractor,
            idle_minutes=idle_minutes, force=force)
        fs["state"] = new_state
        if thought:
            fs["thoughts"] = state_mod.add_thought(fs["thoughts"], thought, kind="reflect")
            self.save_state()
        return thought

    def would_speak_now(self, user_id, affection=0, stage_key="1", cfg=None, now=None):
        """结合精力 / 心情 / 静默时段 / 说话意愿度，判断此刻「想不想主动开口」。

        返回 (是否愿意说话: bool, 中文原因: str)
        """
        fs = self.friend_state(user_id)
        return state_mod.speaking_decision(
            state=fs["state"], emotion=fs["emotion"], relationship=fs["relationship"],
            affection=affection, stage_key=stage_key, cfg=cfg or {}, now=now)

    # ---------------- 门面：提示词与展示 ----------------

    def prompt_block(self, user_id, incoming_text="", stage_key="1", affection=0,
                     bot_profile=None, stage_name=None, gap_minutes=None):
        """组装注入 system prompt 的「内心世界」段落。"""
        fs = self.friend_state(user_id)
        bank = self.friend_bank(user_id)
        # 人设可能改过性别/年龄/名字：把锚定里的身份同步过来（修掉写死的旧身份）
        if bot_profile:
            changed, anchoring = personality_mod.sync_anchoring_identity(
                fs.get("anchoring"), bot_profile)
            if changed:
                fs["anchoring"] = anchoring
                self.save_state()
        if gap_minutes is None:
            gap_minutes = self.minutes_since_last_friend_msg(user_id)
        return prompt_mod.build_mind_block(
            fs=fs, bank=bank, user_id=user_id, incoming_text=incoming_text,
            stage_key=stage_key, affection=affection, bot_profile=bot_profile or {},
            stage_name=stage_name, gap_minutes=gap_minutes,
            last_chat_ts=self.last_chat_ts(user_id))

    def minutes_since_last_friend_msg(self, user_id):
        """距上次对方发消息过了多少分钟。

        注意：on_friend_message 一收到消息就把 last_friend_msg 刷新成 now，
        所以这里要用消息到达前记下的 last_gap_minutes（见 on_friend_message）。
        没有过记录时返回 None。
        """
        try:
            fs = self.friend_state(user_id)
            st = fs.get("state") or {}
            gap = st.get("last_gap_minutes")
            if gap is not None:
                return max(0, int(float(gap)))
            ts = float(st.get("last_friend_msg") or 0.0)
            if not ts:
                return None
            return max(0, int((state_mod.now_ts() - ts) / 60.0))
        except Exception:
            return None

    def last_chat_ts(self, user_id):
        """最近一次跟 TA 说过话的时间戳（谁先开口都算），没有记录返回 0。"""
        try:
            fs = self.friend_state(user_id)
            st = fs.get("state") or {}
            return float(st.get("last_chat_ts") or 0.0)
        except Exception:
            return 0.0

    def unanswered_count(self, user_id):
        """连续几次我发了消息、TA 还没回（赌气机制用）。"""
        try:
            fs = self.friend_state(user_id)
            st = fs.get("state") or {}
            return int(st.get("unanswered") or 0)
        except Exception:
            return 0

    def note_unanswered(self, user_id):
        """记一笔「我发了消息、TA 还没回」。"""
        fs = self.friend_state(user_id)
        fs["state"] = state_mod.state_note_unanswered(fs["state"])
        self.save_state()
        return fs["state"].get("unanswered")

    def guard_reply(self, user_id, reply_text, stage_key="1", prompt_text=None,
                    incoming_text=""):
        """一致性守卫（借鉴 Ai-Companion 的 coherence_guard）。

        校验回复是否与已记住的事实冲突 / 是否出戏，返回 (ok, 原因)。
        prompt_text 传入本次用的 system prompt，可额外识别「原样念提示词」。
        incoming_text 传入后，额外检查「答非所问」和「套话模板」。
        """
        bank = self.friend_bank(user_id)
        fs = self.friend_state(user_id)
        return prompt_mod.guard_reply(reply_text, bank=bank, anchoring=fs["anchoring"],
                                     prompt_text=prompt_text,
                                     incoming_text=incoming_text,
                                     stage_key=stage_key)

    def snapshot(self, user_id, stage_key="1", affection=0):
        """给网页控制台用的可读快照。"""
        fs = self.friend_state(user_id)
        bank = self.friend_bank(user_id)
        return {
            "emotion": emotion_mod.emotion_snapshot(fs["emotion"]),
            "relationship": emotion_mod.relationship_snapshot(
                fs["relationship"], affection=affection, stage_key=stage_key),
            "personality": personality_mod.personality_snapshot(fs["personality"]),
            "state": state_mod.state_snapshot(fs["state"], fs["emotion"], fs["relationship"]),
            "anchoring": fs["anchoring"],
            "quirks": fs["quirks"],
            "milestones": list(reversed(fs["milestones"][-12:])),
            "thoughts": list(reversed(fs["thoughts"][-8:])),
            "memory": memory_mod.bank_snapshot(bank),
        }

    def forget_memory(self, user_id, item_id):
        """删掉一条记忆（网页上可手动忘记）。返回是否删掉了。"""
        bank = self.friend_bank(user_id)
        ok = memory_mod.remove_item(bank, item_id)
        if ok:
            self.save_bank(force=True)
        return ok

    def purge_friend(self, user_id):
        """彻底忘记某个好友（记忆银行 + 内心状态），用于隐私清理。"""
        with self.store.state_lock:
            self.store.state.setdefault("friends", {}).pop(user_id, None)
        with self.store.bank_lock:
            self.store.bank.setdefault("friends", {}).pop(user_id, None)
        self.save_all(force=True)


def get_mind(base_dir=None):
    """获取全局 Mind 实例（进程内单例，线程安全）。"""
    global _mind_instance
    with _mind_lock:
        if _mind_instance is None:
            _mind_instance = Mind(base_dir=base_dir)
        return _mind_instance


def reset_mind_cache(base_dir=None):
    """丢弃当前实例并重新加载（测试或改配置后调用）。"""
    global _mind_instance
    with _mind_lock:
        _mind_instance = Mind(base_dir=base_dir)
        return _mind_instance
