# -*- coding: utf-8 -*-
"""원문 -> 첨삭 -> SVG. 서버가 엔진을 부르는 유일한 경로다.

게이트를 여기서 다시 조립하지 않는다. `chumsak_app.assemble`이 단일 조립기다.
"""
import os
import time

import chumsak_app as CA
import llm_host as LH
import llm_models as LM
import wongoji_svg as WS

HOST = None          # 커널에서 실행할 때 server_pipeline.HOST = host 로 주입한다


def get_kiwi():
    if not hasattr(get_kiwi, "_k"):
        from kiwipiepy import Kiwi
        get_kiwi._k = Kiwi()
    return get_kiwi._k


def get_host():
    if os.environ.get("CHUMSAK_NO_LLM"):
        return None
    if HOST is not None:
        return HOST
    return LH.get_host()


def make_spec(text, drawn, review, extra=None, title=None):
    """제목은 본문 바깥이다.

    렌더러가 제목을 가운데 정렬로 따로 앉히고 `base=-1`을 주어 부호가 붙지 않는다.
    본문에 섞으면 첫 행이 밀리고 `rule_indent`가 제목을 문단으로 보아 들여쓰기표를
    잘못 단다. 원고지에서 제목 행은 문단이 아니다.
    """
    spec = {"text": text, "indent": CA.layout_indent(text), "ncols": 20,
            "double_space": True,
            "corrections": drawn, "review": review or {}}
    if title:
        spec["title"] = title
    if extra:
        spec.update(extra)
    return spec


def run_pipeline(text, grade="초등 6학년", focus=None, llm_items=8, indirect=False,
                 title=None, row_joins=None):
    """규칙 계층 + (가능하면) LLM 계층 -> 게이트 -> SVG."""
    kiwi = get_kiwi()
    rules = CA.rule_layer(text, kiwi)
    llm, review, refused = [], {}, []
    errors = []
    # 공급자를 차례로 시도하되 전체 예산을 넘기지 않는다. 느린 공급자 하나가
    # 다음 공급자 몫까지 먹으면 함수 제한에 걸려 규칙 계층 결과마저 못 낸다.
    budget = LM.LLM_TIMEOUT * 1.5
    started = time.time()
    for provider, host in LH.iter_hosts():
        if time.time() - started > budget:
            errors.append("남은 공급자를 건너뛰었다: LLM 예산 %.0f초 초과" % budget)
            break
        try:
            llm, review, refused = CA.llm_layer(text, host, grade=grade,
                                                max_items=llm_items)
            errors = []
            break
        except Exception as exc:
            errors.append("%s: %s" % (provider, exc))
    if errors:
        refused = [{"kind": "-", "target": "", "reason": "",
                    "drop_reason": "LLM 계층 실패: " + " | ".join(errors)}]
    drawn, held, dropped = CA.assemble(text, rules, llm, refused=refused,
                                       focus=focus, max_items=CA.MAX_SHEET_ITEMS,
                                       row_joins=row_joins)
    if indirect:
        drawn = CA.to_indirect(drawn)
    spec = make_spec(text, drawn, review, title=title)
    built = WS.build(spec)
    return {"svg": built["svg"], "data": built["data"],
            "gate": CA.strip_span(dropped),
            "counts": {"rule": len(rules), "llm": len(llm), "drawn": len(drawn),
                       "held": len(held), "dropped": len(dropped)},
            "spec": spec}
