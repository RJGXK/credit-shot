# -*- coding: utf-8 -*-
"""core/nav.py —— 「从上级目录跳转」的统一导航层。

为什么需要这一层
----------------
政府/司法站点普遍有 WAF（瑞数/知道创宇等）。它们对**直接输入网址直达**
的请求判定更严：瑞数会先返回一张 521 的「Environment Checking」挑战页，
带 Referer 的正常导航则直接放行。用户实测也确认了这一点：
「网站都不要直接输入查询网站，都要从上级目录进行跳转，直接跳转到目标网站，
会被检测异常」。

所以统一做法：**先打开站点的上级目录页 → 在页面上找到指向目标的链接并点击**
（点击产生的导航天然带 Referer），而不是 page.goto 目标 URL。

每个站点配一条「入口链」：
    ENTRY_CHAINS = {
        "gsxt": [
            {"landing": "https://www.samr.gov.cn/",      # 上级目录：市场监管总局
             "match": "gsxt.gov.cn"},                    # 落地页上找含此域的链接
            {"landing": "https://www.gsxt.gov.cn/",      # 兜底：直接进站点首页
             "match": ""},
        ],
        ...
    }

同时解决另一个实测坑：**站点自己在 goto 期间发起跳转**会把
`page.goto` 打断，抛
``Navigation to "..." is interrupted by another navigation to "..."``。
裁判文书网每次访问都会从 ``/`` 跳到 ``/website/wenshu/<id>/index.html``，
所以这里统一用 :func:`goto` 包装，容忍这类打断（打断后页面其实已经在目标站）。
"""
from __future__ import annotations

import time

from core.errors import Aborted, Skipped

__all__ = [
    "goto", "goto_via_landing", "ENTRY_CHAINS", "landing_for",
    "click_matching_link", "nav_state", "site_referer",
]


#: 各站点的「上个网站」（Referer）。
#: 为什么要统一带：瑞数/知道创宇这类 WAF 会把「无来源直达」判成异常请求。
#: gsxt 的实测表现就是——首页能开，但点【查询】毫无反应，
#: 刷新后提示「当前IP请求异常 / 您的IP最近有可疑的攻击行为」。
#: 凡是程序主动 page.goto 本站页面（兜底直连、跳结果页等），一律带上这里的值。
SITE_REFERERS = {
    # 公示系统：上级是市场监管总局（入口链第一条落地页）
    "gsxt": "https://www.samr.gov.cn/",
    # 信用中国：上级是中央政府门户
    "creditchina": "https://www.gov.cn/",
    # 政府采购网：同站首页（从首页进监督检查，是站点自己设计的路径）
    "ccgp": "https://www.ccgp.gov.cn/index.shtml",
    # 住建部：上级是住建部官网
    "mohurd": "https://www.mohurd.gov.cn/",
    # 军队采购网：同站首页
    "plap": "https://www.plap.mil.cn/freecms-glht/site/juncai/index.htm",
    # 执行信息公开网：同站首页
    "zxgk": "https://zxgk.court.gov.cn/shouye/index.html",
    # 裁判文书网：上级是最高人民法院官网
    "wenshu": "https://www.court.gov.cn/",
    # 认监委：上级是认监委官网
    "cnca": "https://www.cnca.gov.cn/",
}


def site_referer(site_key: str) -> str:
    """取某站点的默认 Referer（上个网站）；没有配置就退回入口链首条落地页。"""
    ref = SITE_REFERERS.get(site_key) or ""
    if ref:
        return ref
    for step in landing_for(site_key):
        if step.get("landing"):
            return str(step["landing"])
    return ""


#: 全局可中断等待钩子。引擎启动时注册成 control.wait，
#: 这样导航过程中的等待也能响应【中止】/【跳过此步】。
_NAP = None


def set_nap(fn) -> None:
    """注册可中断等待函数（引擎调用一次）。"""
    global _NAP
    _NAP = fn


def nap(seconds: float) -> None:
    """等待 N 秒；已注册钩子时随时可被中止/跳过打断。"""
    if _NAP is not None:
        _NAP(seconds)
    else:
        time.sleep(seconds)


#: 各站点的「入口链」：按顺序尝试，先命中先用。
#: landing    = 上级目录页；
#: match      = 在落地页里找链接时的关键词（**按 host 精确匹配优先**）；
#: expect_host= 点完链接后期望到达的 host（不等就换下一条链）。
ENTRY_CHAINS = {
    # 国家企业信用信息公示系统：直连必被瑞数拦成白页，
    # 必须先落到「国家市场监督管理总局」再点「国家企业信用信息公示系统」。
    # 注意 samr 首页上还有 ypzsx/tspjg/xwqy 等 gsxt 子站，
    # 所以必须用 host 精确匹配 www.gsxt.gov.cn。
    # **不再提供「直接打开 gsxt 首页」的兜底**：用户实测直接输入网址会被判审核不通过，
    # 必须一步一步点进去；两条总局入口都失败就报错，交给人工处理。
    "gsxt": [
        {"landing": "https://www.samr.gov.cn/", "match": "www.gsxt.gov.cn",
         "expect_host": "www.gsxt.gov.cn"},
        {"landing": "https://www.samr.gov.cn/xw/", "match": "www.gsxt.gov.cn",
         "expect_host": "www.gsxt.gov.cn"},
    ],
    # 信用中国：直连返回 412，走政府门户跳转
    "creditchina": [
        {"landing": "https://www.gov.cn/", "match": "www.creditchina.gov.cn",
         "expect_host": "www.creditchina.gov.cn"},
        {"landing": "https://www.creditchina.gov.cn/", "match": ""},
    ],
    # 中国政府采购网：直连 403，走同域的上级目录
    "ccgp": [
        {"landing": "https://www.ccgp.gov.cn/index.shtml", "match": "www.ccgp.gov.cn",
         "expect_host": "www.ccgp.gov.cn"},
        {"landing": "https://www.ccgp.gov.cn/", "match": ""},
    ],
    # 住建部：走同域首页（本身就是站点根目录）
    "mohurd": [
        {"landing": "https://jzsc.mohurd.gov.cn/home", "match": "jzsc.mohurd.gov.cn",
         "expect_host": "jzsc.mohurd.gov.cn"},
        {"landing": "https://jzsc.mohurd.gov.cn/home", "match": ""},
    ],
    # 军队采购网（只从首页点进去；不再直连监督处罚子页 —— 直接输网址会被判异常）
    "plap": [
        {"landing": "https://www.plap.mil.cn/freecms-glht/site/juncai/index.htm",
         "match": "www.plap.mil.cn", "expect_host": "www.plap.mil.cn"},
    ],
    # 最高法失信被执行人网（只从首页点进去；不再直连 /shixin/ 子页）
    "zxgk": [
        {"landing": "https://zxgk.court.gov.cn/shouye/index.html",
         "match": "zxgk.court.gov.cn", "expect_host": "zxgk.court.gov.cn"},
    ],
    # 中国裁判文书网：首页即上级目录，站内再点「登录 / 高级检索」
    "wenshu": [
        {"landing": "https://wenshu.court.gov.cn/", "match": ""},
    ],
    # 全国认证认可信息公共服务平台：上级目录是国家认监委官网，
    # 从认监委首页点「认证认可信息公共服务平台」进站（直连易被判异常 IP）。
    # 注意：认监委官网上第一个 cx.cnca.cn 链接指向的是「认证结果综合查询」
    # （/CertECloud/result/skipResultList），不是首页 —— 必须用 match_path
    # 精确挑「/CertECloud/index/index/page」那个链接，否则会跳到结果页。
    "cnca": [
        {"landing": "https://www.cnca.gov.cn/", "match": "cx.cnca.cn",
         "expect_host": "cx.cnca.cn",
         "match_path": "/CertECloud/index/index/page",
         "expect_path": "/CertECloud/index/index/page"},
        {"landing": "https://www.cnca.gov.cn/xxgk/", "match": "cx.cnca.cn",
         "expect_host": "cx.cnca.cn",
         "match_path": "/CertECloud/index/index/page",
         "expect_path": "/CertECloud/index/index/page"},
        {"landing": "https://cx.cnca.cn/CertECloud/index/index/page", "match": ""},
    ],
}


def landing_for(site_key: str) -> list:
    """取某站点的入口链。"""
    return ENTRY_CHAINS.get(site_key, [])


def _is_interrupted(exc: Exception) -> bool:
    """判断异常是不是「站点自己跳走了」导致的导航打断。"""
    text = str(exc).lower()
    return ("interrupted by another navigation" in text
            or "navigation to" in text and "interrupted" in text)


def goto(page, url: str, timeout_ms: int = 45000,
         wait_until: str = "domcontentloaded", log=print,
         referer: str = "") -> bool:
    """打开 URL，容忍「站点自跳转打断」。

    裁判文书网、gsxt 都会在 goto 期间自己发起跳转，Playwright 会抛
    ``Navigation ... is interrupted by another navigation to ...``。
    这种情况下页面**其实已经到达了目标站**，不算失败。

    referer 不为空时，给这次导航带上 ``Referer`` 头（「携带上个网站的信息」）。
    瑞数/知道创宇这类 WAF 会把「无来源直达」判成异常请求——
    用户实测 gsxt 就是这个表现：页面能开，但点查询毫无反应，
    刷新后直接提示「当前IP请求异常 / 您的IP最近有可疑的攻击行为」。

    返回是否成功（打断也算成功）。
    """
    kwargs = {}
    if referer:
        kwargs["referer"] = referer
    try:
        resp = page.goto(url, wait_until=wait_until, timeout=timeout_ms, **kwargs)
        # 4xx/5xx 必须进日志：gsxt 的 400 就是「会话票据被判废」的典型表现，
        # 不打出来根本不知道是站点拒绝，而不是页面没渲染。
        try:
            code = getattr(resp, "status", None) if resp is not None else None
        except Exception:
            code = None
        if isinstance(code, int) and code >= 400:
            log("  ⚠ 站点返回 HTTP %d：%s" % (code, url[:70]))
        return True
    except Exception as exc:
        if _is_interrupted(exc):
            log("  ↻ 站点在跳转过程中自行跳转，已跟随到新页面")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            return True
        raise


def nav_state(page) -> dict:
    """读当前页面的基本状态（用于判断有没有被 WAF 拦成白页）。"""
    try:
        return page.evaluate("""()=>({
          url: location.href,
          title: document.title || '',
          len: (document.body ? (document.body.innerText||'').length : 0),
          head: (document.body ? (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200) : ''),
          blank: !document.body || (document.body.innerText||'').trim().length < 20,
          checking: /Environment Checking|环境检测|安全验证|请稍候/i.test(document.title||''),
          denied: /拒绝访问|你没有查看此页面的用户权限|Access Denied|403 Forbidden/i
                  .test((document.body ? document.body.innerText : '')
                        + ' ' + (document.title||'')),
        })""")
    except Exception:
        return {}


def click_matching_link(page, match: str, log=print,
                        expect_host: str = "", match_path: str = "",
                        expect_path: str = "") -> str:
    """在当前页面里点一个链接。

    匹配优先级（**必须按 host 精确匹配优先**）：
      1. 链接的 host 与 match 完全相同 —— 否则像 samr 首页上
         「特殊食品信息查询平台」(ypzsx.gsxt.gov.cn) 会先于
         「国家企业信用信息公示系统」(www.gsxt.gov.cn) 被命中；
      2. 链接的 host 以 match 结尾（同域子路径）；
      3. href 里含 match；
      4. 链接文字含 match。

    match_path 不为空时，**先在路径匹配的链接里挑**（挑不到才退回全量）。
    认监委官网上第一个 cx.cnca.cn 链接指向的是「认证结果综合查询」
    （/CertECloud/result/skipResultList），而不是首页
    （/CertECloud/index/index/page）—— 不限定路径就会跳错页面。

    expect_host 不为空时，点完会校验当前页 host 是否包含它；
    不含就返回 'MISMATCH'，让调用方换下一条入口链。
    expect_path 同理，校验落地的路径片段。

    返回 'CLICK:<href>' / 'NONE' / 'MISMATCH' / 'ERR:<原因>'。
    """
    if not match:
        return "NONE"
    js = """
    (arg)=>{
      const kw=arg.kw, wantPath=arg.path||'';
      const norm=s=>(s||'').replace(/\\s+/g,'');
      const as=[...document.querySelectorAll('a[href]')];
      const hostOf=a=>{try{return new URL(a.href,location.href).host;}catch(e){return '';}};
      const pathOf=a=>{try{return new URL(a.href,location.href).pathname||'';}catch(e){return '';}};
      // 先在路径匹配的链接里挑，挑不到再退回全量
      let pool=as;
      if(wantPath){
        const sub=as.filter(a=>pathOf(a).indexOf(wantPath)>=0);
        if(sub.length) pool=sub;
      }
      let hit=null;
      // 1) host 完全相同
      hit=pool.find(a=>hostOf(a)===kw);
      // 2) host 以 kw 结尾（子域）
      if(!hit) hit=pool.find(a=>{const h=hostOf(a); return h&&h.endsWith('.'+kw);});
      // 3) href 含关键词
      if(!hit) hit=pool.find(a=>{try{return (a.href||'').indexOf(kw)>=0;}catch(e){return false;}});
      // 4) 文字匹配
      if(!hit) hit=pool.find(a=>norm(a.innerText||a.textContent||'').indexOf(norm(kw))>=0);
      if(!hit) return 'NONE';
      hit.click();
      return 'CLICK:'+hit.href.slice(0,90);
    }
    """
    try:
        r = page.evaluate(js, {"kw": match, "path": match_path})
    except Exception as exc:
        return "ERR:%s" % str(exc).splitlines()[0][:80]
    if not str(r).startswith("CLICK"):
        return str(r)
    log("  点链接 → %s" % str(r)[6:60])
    # 等跳转完成
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    nap(2.0)
    if expect_host:
        try:
            host = page.evaluate("()=>location.host")
        except Exception:
            host = ""
        # host 不匹配有两种情况：
        #   · 跳到了别的站（MISMATCH）—— 换下一条入口链
        #   · 链接带 target=_blank 开了新标签页（POPUP）—— 切到新标签页继续
        #
        # 注意：认监委官网给的链接是**加速代理地址**，形如
        #   ``1.443.https.cx.cnca.cn---xxxx.www.cnca.gov.cn.365cyd.com.cn:11080``
        # host 并不等于 cx.cnca.cn，但里面**包含**它 —— 所以这里用「包含」判定，
        # 不能用相等判定，否则会被误判成跳错站。
        if host and expect_host not in host:
            newp = _find_new_page(page, expect_host)
            if newp is not None:
                log("  → 链接开了新标签页，已切换过去")
                try:
                    newp.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                return "POPUP:" + (newp.url or "")
            return "MISMATCH:%s" % host
    if expect_path:
        try:
            path = page.evaluate("()=>location.pathname")
        except Exception:
            path = ""
        if path and expect_path not in path:
            return "MISMATCH:path=%s" % path
    return str(r)


def _find_new_page(page, host: str):
    """找同域的新标签页（链接带 target=_blank 时站点会开新窗口）。

    host 可以是完整 host（如 www.gsxt.gov.cn）。
    新标签页刚打开时 URL 可能还没定稿，所以先按 host 找，
    找不到再看有没有非当前页的新页。
    """
    try:
        ctx = page.context
    except Exception:
        ctx = None
    if ctx is None:
        return None
    try:
        pages = list(ctx.pages)
    except Exception:
        return None
    # 1) host 精确匹配
    for p in pages:
        if p is page:
            continue
        try:
            u = p.url or ""
        except Exception:
            continue
        if host and host in u:
            return p
    # 2) 兜底：唯一一个新页，且不是空白页
    others = [p for p in pages if p is not page]
    if len(others) == 1:
        try:
            u = others[0].url or ""
        except Exception:
            u = ""
        if u and u != "about:blank":
            return others[0]
    return None


def _wait_ready_patient(page, timeout: float = 20.0, allow_reload: bool = False,
                        log=print) -> dict:
    """耐心等页面真正可用（WAF 环境检测/慢渲染期间不急着判失败）。

    allow_reload=True 时：等待过半仍空白/被拒就自动 reload 一次再等——
    部分站点（认监委加速代理）首次落地必须刷新一次才真正进入。
    返回最终的 nav_state；可用时 len>200 且非 blank 非 checking。
    """
    deadline = time.time() + timeout
    reloaded = False
    st = nav_state(page)
    while time.time() < deadline:
        if (st.get("len", 0) > 200 and not st.get("blank")
                and not st.get("checking") and not st.get("denied")):
            return st
        # 过半还卡着：刷新一次（很多政务站首次落地需要手动刷新才放行）
        if (allow_reload and not reloaded
                and time.time() > deadline - timeout / 2.0
                and (st.get("blank") or st.get("denied"))):
            log("  ↻ 页面仍未就绪，自动刷新一次再等放行…")
            reloaded = True
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                try:
                    page.reload()
                except Exception:
                    pass
            nap(2.0)
        nap(1.5)
        st = nav_state(page)
    return st


def goto_via_landing(page, site_key: str, log=print,
                     timeout_ms: int = 45000) -> dict:
    """按入口链「从上级目录跳转」进入站点，返回最终页面状态。

    流程：落地页 → 站内匹配链接并点击 → 落地成功。
    链接点不到时退化为直接打开落地页（多数站点首页本身就是上级目录）。
    """
    chain = landing_for(site_key)
    if not chain:
        return {"ok": False, "reason": "没有配置入口链", "page": page}
    last = {}
    init_page = page
    for step in chain:
        landing = step.get("landing") or ""
        match = step.get("match") or ""
        expect_host = step.get("expect_host") or ""
        match_path = step.get("match_path") or ""
        expect_path = step.get("expect_path") or ""
        referer = step.get("referer") or ""
        # 「直连兜底」条目（没有 match，落地页本身就是目标站）必须带 Referer，
        # 否则等于裸奔进站，会被 WAF 记成异常来源。
        if not referer and not match:
            referer = site_referer(site_key)
        if not landing:
            continue
        try:
            goto(page, landing, timeout_ms=timeout_ms, log=log, referer=referer)
        except Exception as exc:
            log("  ⚠ 落地页打开失败(%s)：%s" % (landing[:44], str(exc).splitlines()[0][:70]))
            last = {"ok": False, "reason": str(exc)[:120]}
            continue
        nap(2.5)
        st = nav_state(page)
        if st.get("denied"):
            log("  ↻ 落地页被拒绝访问（%s），换下一条入口链" % landing[:40])
            last = {"ok": False, "reason": "落地页拒绝访问"}
            continue
        if st.get("checking"):
            log("  ⓘ 落地页正在做环境检测（%s），等待放行…" % landing[:40])
            for _ in range(20):
                nap(2.0)
                st = nav_state(page)
                if st.get("denied"):
                    log("  ↻ 环境检测后仍被拒绝访问，换下一条入口链")
                    st = {"denied": True}
                    break
                if not st.get("checking"):
                    break
            if st.get("denied"):
                last = {"ok": False, "reason": "落地页拒绝访问"}
                continue
        if match:
            r = click_matching_link(page, match, log=log, expect_host=expect_host,
                                    match_path=match_path, expect_path=expect_path)
            if str(r).startswith("POPUP"):
                # 链接开了新标签页：把后续操作切到那个页面
                newp = _find_new_page(page, expect_host)
                if newp is None:
                    # 点击后新页 URL 才定稿，再等一下找
                    for _ in range(6):
                        nap(1.5)
                        newp = _find_new_page(page, expect_host)
                        if newp is not None:
                            break
                if newp is not None:
                    try:
                        newp.wait_for_load_state("domcontentloaded", timeout=20000)
                    except Exception:
                        pass
                    nap(2.0)
                    st = _wait_ready_patient(newp, timeout=20.0)
                    if expect_path:
                        try:
                            cur = newp.evaluate("()=>location.pathname")
                        except Exception:
                            cur = ""
                        if cur and expect_path not in cur:
                            log("  ↻ 落地路径不是 %s，换下一条入口链" % expect_path)
                            try:
                                newp.close()
                            except Exception:
                                pass
                            page = init_page
                            last = {"ok": False, "reason": "落地路径不符"}
                            continue
                    if st.get("len", 0) > 200 and not st.get("blank"):
                        log("  ✔ 经上级目录跳转进入：%s" % str(st.get("url", ""))[:70])
                        return {"ok": True, "state": st, "via": landing,
                                "page": newp}
                    last = {"ok": False, "reason": "新标签页仍是空白页"}
                    try:
                        newp.close()
                    except Exception:
                        pass
                    page = init_page
                else:
                    last = {"ok": False, "reason": "新标签页未找到"}
                continue
            if str(r).startswith("MISMATCH"):
                log("  ↻ 跳到了别的站（%s），换下一条入口链" % str(r)[9:40])
                last = {"ok": False, "reason": "跳转到了非目标站"}
                continue
            if str(r).startswith("CLICK"):
                nap(2.5)
                # WAF 环境检测/慢渲染期间别急着判失败
                st = _wait_ready_patient(page, timeout=20.0)
                if expect_path:
                    try:
                        cur = page.evaluate("()=>location.pathname")
                    except Exception:
                        cur = ""
                    if cur and expect_path not in cur:
                        log("  ↻ 落地路径不是 %s，换下一条入口链" % expect_path)
                        last = {"ok": False, "reason": "落地路径不符"}
                        continue
                if st.get("len", 0) > 200 and not st.get("blank"):
                    log("  ✔ 经上级目录跳转进入：%s" % str(st.get("url", ""))[:70])
                    return {"ok": True, "state": st, "via": landing, "page": page}
                last = {"ok": False, "reason": "跳转后仍是空白页"}
            else:
                last = {"ok": False, "reason": "落地页上没有匹配的链接"}
                continue
        else:
            # 没有匹配词：落地页本身就是目标站入口
            # WAF 环境检测（瑞数/加速乐）可能要十几秒才放行，耐心等；
            # 认监委等站点首次落地常需刷新一次才真正进入 → allow_reload=True
            st = _wait_ready_patient(page, timeout=30.0, allow_reload=True, log=log)
            if st.get("len", 0) > 200 and not st.get("blank"):
                log("  ✔ 经上级目录进入：%s" % str(st.get("url", ""))[:70])
                return {"ok": True, "state": st, "via": landing, "page": page}
            last = {"ok": False, "reason": "落地页空白"}
    # 全部尝试失败：最后再直接打开一次目标（部分站点有兜底放行）
    log("  ⚠ 入口链全部失败，最后再直接尝试一次")
    return {"ok": False, "reason": last.get("reason", "入口链失败"), "state": last, "page": page}
