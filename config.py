# -*- coding: utf-8 -*-
"""企业信用一键截图工具 —— 站点/采集项目录与默认参数。

覆盖 7 个站点、25 个采集项，按「站点分组 → 全局编号」编排。
编号即输出文件名前缀，也决定 PDF 汇总的合并顺序（01→02→…）。

每个采集项带几个关键字段：
  kind    决定 engine 里用哪个流程实现（同一站点多个采集项可共用流程）；
  group   决定哪些采集项共享同一次浏览会话（共用会话的先做一次进入动作，
          再逐项切 tab 截图，避免每个 tab 都重新搜一遍）；
  tab     该采集项在站点页面上对应的 tab 文字；
  subject 查询主体类型（决定这个名单能按「单位」查还是「人员」查）：
          "company"  仅支持单位（企业名称 + 统一社会信用代码）；
          "person"   仅支持人员（人员姓名 + 身份证号）；
          "either"   两种都支持（按模式切换）。

「查询主体」在 GUI 里用一行一条、竖线分隔，并先选查询模式：
    单位模式：企业名称|统一社会信用代码
    人员模式：人员姓名|身份证号
两种模式各查各的，互不混用。
"""

import os

# 程序版本号（日志头、关于信息、安装包统一引用）
APP_VERSION = "2.2.8"

# ---------------------------------------------------------------- 站点分组
SITES = [
    {
        "key": "creditchina_pub",
        "name": "信用中国 - 信息公示",
        "short": "信用公示",
        "platform": "信用中国（信息公示）",
        "platform_url": "https://www.creditchina.gov.cn/xinxigongshi/",
        "steps": [
            {"no": "01", "mark": "①", "key": "cc_shixin", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 严重失信主体名单查询",
             "short": "信用中国严重失信主体名单",
             "url": "https://www.creditchina.gov.cn/xinxigongshi/shixinheimingdan/"},
            {"no": "02", "mark": "②", "key": "cc_jingyingyichang", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 经营（活动）异常名录查询",
             "short": "信用中国经营异常名录",
             "url": "https://www.creditchina.gov.cn/xinxigongshi/zhongdianguanzhushixinmingdan/"},
        ],
    },
    {
        "key": "creditchina_special",
        "name": "信用中国 - 专项查询",
        "short": "信用专项",
        "platform": "信用中国（专项查询）",
        "platform_url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/",
        "steps": [
            {"no": "03", "mark": "③", "key": "cc_aqsc", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 安全生产严重失信主体名单（法人）",
             "short": "信用中国安全生产严重失信",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/aqsc/"},
            {"no": "04", "mark": "④", "key": "cc_aqsczrr", "kind": "creditchina_person", "group": "cc",
             "subject": "person",
             "title": "信用中国 - 安全生产严重失信主体名单（自然人）",
             "short": "信用中国安全生产严重失信（自然人）",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/aqsczrr/"},
            {"no": "05", "mark": "⑤", "key": "cc_shuishou", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 重大税收违法失信主体名单",
             "short": "信用中国重大税收违法",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/zhongdashuishouweifaanjian/"},
            {"no": "06", "mark": "⑥", "key": "cc_shixinbeizhixingren", "kind": "zxgk", "group": "zxgk",
             "subject": "either",
             "title": "信用中国 - 失信被执行人（跳转最高法失信被执行人网）",
             "short": "失信被执行人查询",
             "platform": "最高人民法院失信被执行人信息网",
             "platform_url": "https://zxgk.court.gov.cn/shixin/",
             "url": "https://zxgk.court.gov.cn/shixin/"},
            {"no": "07", "mark": "⑦", "key": "cc_tongji", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 统计严重失信企业名单",
             "short": "信用中国统计严重失信",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/zdlycx/"
                    "?tablename=credit_gjtjj_fr_tjsyzsxqy&gsName=%E7%BB%9F%E8%AE%A1%E4%B8%A5%E9%87%8D%E5%A4%B1%E4%BF%A1%E4%BC%81%E4%B8%9A%E5%90%8D%E5%8D%95"},
            {"no": "08", "mark": "⑧", "key": "cc_shehui", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 社会组织严重违法失信名单",
             "short": "信用中国社会组织严重违法",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/shzz/"},
            {"no": "09", "mark": "⑨", "key": "cc_zckjs", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 注册会计师行业严重失信主体名单（法人和非法人组织）",
             "short": "信用中国注册会计师严重失信",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/zckjs/"},
            {"no": "10", "mark": "⑩", "key": "cc_zhengfucaigou", "kind": "creditchina", "group": "cc",
             "subject": "company",
             "title": "信用中国 - 政府采购严重违法失信行为记录名单（法人和非法人组织）",
             "short": "信用中国政府采购严重违法",
             "url": "https://www.creditchina.gov.cn/zhuanxiangchaxun/zhengfucaigouyanzhongweifashixinmingdan/"},
        ],
    },
    {
        "key": "ccgp",
        "name": "中国政府采购网",
        "short": "政府采购",
        "platform": "中国政府采购网",
        "platform_url": "https://www.ccgp.gov.cn/",
        "steps": [
            {"no": "11", "mark": "⑪", "key": "ccgp_yanzhongweifa", "kind": "ccgp", "group": "ccgp",
             "subject": "company",
             "title": "中国政府采购网 - 政府采购严重违法失信行为记录名单",
             "short": "政采网严重违法失信",
             "url": "https://www.ccgp.gov.cn/search/cr/",
             "home": "https://www.ccgp.gov.cn/"},
        ],
    },
    {
        "key": "mohurd",
        "name": "全国建筑市场监管公共服务平台（住建部）",
        "short": "住建部",
        "platform": "全国建筑市场监管公共服务平台（住建部）",
        "platform_url": "https://jzsc.mohurd.gov.cn/home",
        "steps": [
            {"no": "12", "mark": "⑫", "key": "jzsc_zizhi", "kind": "mohurd", "group": "mohurd",
             "subject": "company",
             "title": "住建部 - 企业资质资格",
             "short": "住建部企业资质资格", "tab": "企业资质资格"},
            {"no": "13", "mark": "⑬", "key": "jzsc_buLiang", "kind": "mohurd", "group": "mohurd",
             "subject": "company",
             "title": "住建部 - 不良行为", "short": "住建部不良行为", "tab": "不良行为"},
            {"no": "14", "mark": "⑭", "key": "jzsc_heimingdan", "kind": "mohurd", "group": "mohurd",
             "subject": "company",
             "title": "住建部 - 黑名单记录", "short": "住建部黑名单记录", "tab": "黑名单记录"},
            {"no": "15", "mark": "⑮", "key": "jzsc_shixin", "kind": "mohurd", "group": "mohurd",
             "subject": "company",
             "title": "住建部 - 失信联合惩戒记录", "short": "住建部失信联合惩戒", "tab": "失信联合惩戒记录"},
        ],
    },
    {
        "key": "plap",
        "name": "军队采购网（监督检查）",
        "short": "军队采购",
        "platform": "军队采购网（监督检查）",
        "platform_url": "https://www.plap.mil.cn/freecms-glht/site/juncai/jdjc/index.html",
        "steps": [
            {"no": "16", "mark": "⑯", "key": "mil_quanbu", "kind": "plap", "group": "plap",
             "subject": "either", "person_subject": False,
             "title": "军队采购网 - 全部", "short": "军队采购网全部", "tab": "全部"},
            {"no": "17", "mark": "⑰", "key": "mil_yujing", "kind": "plap", "group": "plap",
             "subject": "either",
             "title": "军队采购网 - 军队采购预警名单", "short": "军队采购网预警名单", "tab": "军队采购预警名单"},
            {"no": "18", "mark": "⑱", "key": "mil_zanting", "kind": "plap", "group": "plap",
             "subject": "either",
             "title": "军队采购网 - 军队采购暂停名单", "short": "军队采购网暂停名单", "tab": "军队采购暂停名单"},
            {"no": "19", "mark": "⑲", "key": "mil_shixin", "kind": "plap", "group": "plap",
             "subject": "either",
             "title": "军队采购网 - 军队采购失信名单", "short": "军队采购网失信名单", "tab": "军队采购失信名单"},
            {"no": "20", "mark": "⑳", "key": "mil_zhengfucaigou", "kind": "plap", "group": "plap",
             "subject": "either", "person_subject": False,
             "title": "军队采购网 - 政府采购失信名单", "short": "军队采购网政府采购失信", "tab": "政府采购失信名单"},
        ],
    },
    {
        "key": "gsxt",
        "name": "国家企业信用信息公示系统",
        "short": "公示系统",
        "platform": "国家企业信用信息公示系统",
        "platform_url": "https://www.gsxt.gov.cn/index.html",
        "steps": [
            {"no": "21", "mark": "㉑", "key": "gsxt_basic", "kind": "gsxt_basic", "group": "gsxt_detail",
             "subject": "company",
             "title": "国家企业信用信息公示系统 - 基础信息（含全部股东及出资详细信息）+ 行政处罚信息 + 列入经营异常名录信息 + 列入严重违法失信名单（黑名单）信息",
             "short": "公示系统企业信用全信息",
             "unstick": True,
             "url": "https://www.gsxt.gov.cn/index.html"},
            {"no": "22", "mark": "㉒", "key": "gsxt_blacklist", "kind": "gsxt_blacklist", "group": "gsxt_blacklist",
             "subject": "company",
             "title": "国家企业信用信息公示系统 - 未列入严重违法失信企业名单（黑名单）",
             "short": "公示系统黑名单",
             "url": "https://www.gsxt.gov.cn/index.html"},
            {"no": "23", "mark": "㉓", "key": "gsxt_admin_penalty", "kind": "gsxt_section",
             "group": "gsxt_detail",
             "subject": "company",
             "title": "国家企业信用信息公示系统 - 行政处罚信息",
             "short": "公示系统行政处罚信息",
             "section": "行政处罚信息",
             "merged_shot": True,
             "url": "https://www.gsxt.gov.cn/index.html"},
            {"no": "24", "mark": "㉔", "key": "gsxt_abnormal", "kind": "gsxt_section",
             "group": "gsxt_detail",
             "subject": "company",
             "title": "国家企业信用信息公示系统 - 列入经营异常名录信息",
             "short": "公示系统经营异常名录信息",
             "section": "列入经营异常名录",
             "merged_shot": True,
             "url": "https://www.gsxt.gov.cn/index.html"},
            {"no": "25", "mark": "㉕", "key": "gsxt_blacklist_listed", "kind": "gsxt_section",
             "group": "gsxt_detail",
             "subject": "company",
             "title": "国家企业信用信息公示系统 - 列入严重违法失信名单（黑名单）信息",
             "short": "公示系统列入严重违法失信名单",
             "section": "列入严重违法失信名单",
             "merged_shot": True,
             "url": "https://www.gsxt.gov.cn/index.html"},
        ],
    },
    {
        "key": "wenshu",
        "name": "中国裁判文书网",
        "short": "裁判文书",
        "platform": "中国裁判文书网",
        "platform_url": "https://wenshu.court.gov.cn/",
        "steps": [
            # ws_flow = party    单位：首页→高级检索→当事人=单位全称、全文=诉讼/仲裁；
            #                       人员：当事人=姓名、全文=身份证号，搜索出结果后再用全文筛诉讼/仲裁。
            # ws_flow = fulltext 全文=单位/人员先搜，搜索出结果后再用全文筛「行贿」。
            {"no": "26", "mark": "㉖", "key": "ws_susong", "kind": "wenshu", "group": "ws",
             "subject": "either",
             "title": "裁判文书网 - 诉讼", "short": "裁判文书网诉讼",
             "case": "诉讼", "ws_flow": "party"},
            {"no": "27", "mark": "㉗", "key": "ws_zhongcai", "kind": "wenshu", "group": "ws",
             "subject": "either",
             "title": "裁判文书网 - 仲裁", "short": "裁判文书网仲裁",
             "case": "仲裁", "ws_flow": "party"},
            {"no": "28", "mark": "㉘", "key": "ws_xinghui", "kind": "wenshu", "group": "ws_xinghui",
             "subject": "either",
             "title": "裁判文书网 - 行贿", "short": "裁判文书网红行贿",
             "case": "行贿", "ws_flow": "fulltext"},
        ],
    },
    {
        "key": "cnca",
        "name": "全国认证认可信息公共服务平台",
        "short": "认监委认证",
        "platform": "全国认证认可信息公共服务平台",
        "platform_url": "https://cx.cnca.cn/CertECloud/index/index/page",
        "steps": [
            {"no": "29", "mark": "㉙", "key": "cnca_list", "kind": "cnca", "group": "cnca",
             "subject": "company",
             "title": "全国认证认可信息公共服务平台 - 证书列表",
             "short": "认监委证书列表", "sub_step": "list"},
            {"no": "30", "mark": "㉚", "key": "cnca_detail", "kind": "cnca", "group": "cnca",
             "subject": "company",
             "title": "全国认证认可信息公共服务平台 - 认证详细信息",
             "short": "认监委认证详细信息", "sub_step": "detail"},
        ],
    },
]

# ---------------------------------------------------------------- 查询模式
# 「单位」和「人员」是两种互斥的查询模式，各自的输入格式与可用名单都不同。
MODE_COMPANY = "company"
MODE_PERSON = "person"
SUBJECT_MODES = ["单位", "人员"]                 # GUI 单选按钮显示的文字
MODE_OF_LABEL = {"单位": MODE_COMPANY, "人员": MODE_PERSON}
LABEL_OF_MODE = {MODE_COMPANY: "单位", MODE_PERSON: "人员"}

# 两种模式各自的输入格式说明（GUI 提示行直接用；保持简短，避免撑宽界面）
MODE_FORMAT = {
    MODE_COMPANY: "企业名称|统一社会信用代码",
    MODE_PERSON: "人员姓名|身份证号",
}
MODE_HINT = {
    MODE_COMPANY: "一行一个，可批量；信用代码可留空，只填企业名称也行",
    MODE_PERSON: "一行一个，可批量；只收录单位的名单会自动置灰不可选",
}


def step_supports(step: dict, mode: str) -> bool:
    """该采集项是否支持当前查询模式。

    subject 字段：
      "company" 只支持单位；"person" 只支持人员；"either" 两种都支持。
    另有 person_subject: False —— 两种模式都放着，但**人员模式下置灰**
    （用户要求：军网的「全部」「政府采购失信名单」不做人员查询，
    这两个 tab 的表单没有「处理主体类型=专家」的个人查询入口）。
    """
    s = step.get("subject", MODE_COMPANY)
    if s == "either":
        if mode == MODE_PERSON and step.get("person_subject") is False:
            return False
        return True
    return s == mode


# ---------------------------------------------------------------- 默认参数
def _default_output_dir() -> str:
    """默认截图输出目录。

    不能写死某个用户的桌面路径 —— 换台电脑就指到不存在的地方了。
    这里按「当前用户的桌面」动态算，取不到就退回用户目录下的同名文件夹。
    """
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_DESKTOPDIRECTORY = 0x0010
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0:
            desktop = buf.value
            if desktop and os.path.isdir(desktop):
                return os.path.join(desktop, "企业信用截图")
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "企业信用截图")


DEFAULTS = {
    "output_dir": _default_output_dir(),
    "browser": "Edge",                 # Edge | Chrome
    "shot_mode": "原图+日期弹窗+信息条",   # 原图 | 原图+信息条 | 原图+日期弹窗 | 原图+日期弹窗+信息条
    "subject_mode": "单位",              # 单位 | 人员
    "pace_seconds": 30,                # 步骤/企业之间的节流间隔（模拟正常使用频率）
    "make_pdf": False,                 # 额外生成 PDF 汇总
    "timeout": 60,                     # 单步超时（秒）
    "manual_timeout": 900,             # 挂起等人工处理（验证码/登录）的时限（秒）
}

BROWSER_CHANNELS = {"Edge": "msedge", "Chrome": "chrome"}
SHOT_MODES = ["原图", "原图+信息条", "原图+日期弹窗", "原图+日期弹窗+信息条"]

# ------------------------------------------------------------------ 登录平台
# 可能需要账号登录的平台清单。
# 「auto」= 该平台已实现自动登录流程（引擎检测到登录页时会自动填账号密码登录）；
#        其它平台 auto=False：公开查询通常免登录，若真的被拦下仍会挂起等人工处理，
#        填了账号密码也会在日志里提示「该平台暂不支持自动登录，请手动登录」。
#
# 用户要求（2026-10-29）：只有**裁判文书网**和**公示系统（gsxt）**保留账号密码配置；
# 信用中国 / 政府采购网 / 住建部 / 军队采购网 / 失信被执行人网 / 认证认可平台
# 全部免登录 —— 不在「账号密码」卡片里出现，界面上少一堆无用输入框。
LOGIN_PLATFORMS = [
    {
        "key": "wenshu",
        "name": "中国裁判文书网",
        "host": "wenshu.court.gov.cn",
        "login_host": "account.court.gov.cn",
        "url": "https://wenshu.court.gov.cn/",
        "account": "手机号",
        "auto": True,
        "hint": "检索前必须登录。账号=注册手机号，密码=登录密码；"
                "登录表单在统一身份认证（account.court.gov.cn）的跨域窗口内。",
    },
    {
        "key": "gsxt",
        "name": "国家企业信用信息公示系统",
        "host": "www.gsxt.gov.cn",
        "url": "https://www.gsxt.gov.cn/index.html",
        "account": "手机号 / 用户名",
        "auto": True,
        "hint": "公开查询免登录；查询/登录时可能触发极验滑块或点选验证，"
                "这类官方打码题型不支持，需人工完成。"
                "站点直连会被判定异常 IP，程序已改为从「国家市场监督管理总局」"
                "跳转进入。",
    },
]

# 需要叠加 Windows 日期/时间面板的两种方式：
# 页面本身用浏览器原生整页截图（内容完整），再把系统日期面板合成到图片右下角。
DATE_POPUP_MODES = ("原图+日期弹窗", "原图+日期弹窗+信息条")
# 需要插入信息条的两种方式
INFO_BAR_MODES = ("原图+信息条", "原图+日期弹窗+信息条")

LOG_READY = [
    "就绪。先选查询类型（单位 / 人员），再填查询主体 → 点【开始截图】→ 验证码请手动输入。",
    "单位模式：每行「企业名称|统一社会信用代码」；人员模式：每行「人员姓名|身份证号」。",
    "两种模式的可用名单不同：切换时下方列表会自动置灰不适用的采集项。",
    "「原图+日期弹窗」= 页面完整整页图 + 右下角系统日期/时间面板（真实屏幕抓取后合成）。",
    "需要登录的平台可在「账号密码」里填账号，引擎会自动登录（目前自动支持裁判文书网）。",
    "首次使用建议点【功能自检】：不开放外网可验证浏览器驱动、截图与日期弹窗是否正常。",
]

# 站点入口
HOME_URLS = {
    "zxgk": "https://zxgk.court.gov.cn/shixin/",
    "ccgp": "https://www.ccgp.gov.cn/",
    "ccgp_list": "https://www.ccgp.gov.cn/search/cr/",
    "mohurd": "https://jzsc.mohurd.gov.cn/home",
    "plap": "https://www.plap.mil.cn/freecms-glht/site/juncai/jdjc/index.html",
    "gsxt": "https://www.gsxt.gov.cn/index.html",
    # 裁判文书网每次访问都会从 / 跳到 /website/wenshu/<随机ID>/index.html，
    # 那个 ID 每次都变，所以这里只能写站点根地址，由程序跟随跳转。
    "wenshu": "https://wenshu.court.gov.cn/",
    "cnca": "https://cx.cnca.cn/CertECloud/index/index/page",
}


def all_steps():
    """按编号顺序展平所有采集项。"""
    out = []
    for site in SITES:
        for st in site["steps"]:
            item = dict(st)
            item["site"] = site["name"]
            # 平台/系统名称与网址：采集项可覆盖站点默认值（如失信被执行人网）
            item.setdefault("platform", site.get("platform") or site["name"])
            item.setdefault("platform_url", site.get("platform_url") or "")
            out.append(item)
    return out


def step_map():
    return {s["key"]: s for s in all_steps()}
