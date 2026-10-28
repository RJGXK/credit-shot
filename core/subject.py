# -*- coding: utf-8 -*-
"""查询主体的解析与判定（纯逻辑，无浏览器依赖）。

两种互斥的查询模式：

    单位模式  一行一条 → 企业名称|统一社会信用代码
    人员模式  一行一条 → 人员姓名|身份证号

两种模式都只取前两段，多写的段一律忽略（不会串味）。
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from config import MODE_COMPANY, MODE_PERSON

__all__ = [
    "Subject", "parse_subject", "split_company", "looks_like_idcard",
    "safe_name", "ILLEGAL_NAME_CHARS",
]

# 文件名里非法的字符（Windows）
ILLEGAL_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def safe_name(name: str) -> str:
    """把任意文本转成能安全用作文件名的片段。"""
    return ILLEGAL_NAME_CHARS.sub("_", name).strip() or "company"


@dataclass
class Subject:
    """一个查询主体。

    两种互斥的模式，字段含义完全不同：

    单位模式（mode=company）：
        一行一条 → 企业名称|统一社会信用代码
        company=企业名称，code=统一社会信用代码

    人员模式（mode=person）：
        一行一条 → 人员姓名|身份证号
        person=人员姓名，idcard=身份证号
    """

    mode: str = MODE_COMPANY
    company: str = ""
    code: str = ""
    person: str = ""
    idcard: str = ""

    @property
    def has_person(self) -> bool:
        return bool(self.person.strip())

    @property
    def is_person_mode(self) -> bool:
        return self.mode == MODE_PERSON

    def label(self) -> str:
        """文件名用的主体标识：单位模式取企业名，人员模式取姓名。"""
        if self.mode == MODE_PERSON:
            return self.person.strip() or "人员"
        return self.company.strip() or self.person.strip() or "主体"

    def keyword(self) -> str:
        """站点通用关键字框里该填什么：人员模式填姓名，单位模式填企业名。"""
        if self.mode == MODE_PERSON:
            return self.person.strip()
        return self.company.strip() or self.person.strip()

    def id_number(self) -> str:
        """身份证号/证件号：优先人员的，否则企业的统一社会信用代码。"""
        return self.idcard.strip() or self.code.strip()

    def describe(self) -> str:
        """日志里的一行主体描述。"""
        if self.mode == MODE_PERSON:
            return "人员 %s%s" % (self.person.strip() or "(未填姓名)",
                                 ("（身份证 %s）" % self.idcard.strip()) if self.idcard.strip() else "")
        return "单位 %s%s" % (self.company.strip() or "(未填企业名称)",
                              ("（%s）" % self.code.strip()) if self.code.strip() else "")


def parse_subject(line: str, mode: str = MODE_COMPANY) -> Subject:
    """按查询模式解析一行主体信息。

    单位模式：企业名称|统一社会信用代码
    人员模式：人员姓名|身份证号

    两种模式都只取前两段，多写的段一律忽略（不会串味）。
    """
    parts = [p.strip() for p in line.split("|")]
    parts += [""] * (4 - len(parts))
    if mode == MODE_PERSON:
        return Subject(mode=MODE_PERSON, person=parts[0], idcard=parts[1])
    return Subject(mode=MODE_COMPANY, company=parts[0], code=parts[1])


def split_company(line: str):
    """兼容旧接口：返回 (企业名称, 统一社会信用代码)。"""
    s = parse_subject(line)
    return s.company, s.code


def looks_like_idcard(value: str) -> bool:
    """粗判是不是身份证号。

    18 位统一社会信用代码同样是 18 位数字，靠「第 7-14 位是合法出生日期」把它区分开：
      914403001922382216 → 01922382 不是日期 → 判定为信用代码
      110101199001011234 → 19900101 是日期 → 判定为身份证号
    """
    v = (value or "").strip().upper()
    if len(v) == 18:
        if not (v[:17].isdigit() and (v[17].isdigit() or v[17] == "X")):
            return False
        try:
            birth = dt.date(int(v[6:10]), int(v[10:12]), int(v[12:14]))
        except ValueError:
            return False
        return 1900 <= birth.year <= dt.date.today().year
    if len(v) == 15:
        return v.isdigit()
    return False
