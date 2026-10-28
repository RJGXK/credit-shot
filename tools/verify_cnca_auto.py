# -*- coding: utf-8 -*-
"""CNCA 真机半自动验证：跑到「极验弹层出现」为止（不需要人工点图）。

验证的是本次改动最关键的三件事：
  1. 能经上级目录进入 CNCA 首页；
  2. 首页填企业名 → 点【查询】→ **整页跳转**到 skipResultList；
  3. 在结果页**再填一次**企业名 → 点【查询】→ 极验弹层**真的弹出**
     （用产品里同一套判据，确认不会误判也不会漏判）。

极验之后的渲染由站点自己的 JS 完成，其 DOM 结构已按前端源码核对过，
这里不再重复验证。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Engine
from platforms.cnca import CncaHandler
from core.errors import EngineError

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca_auto")
COMPANY = "中瑞盛世（北京）建筑有限公司"


class ProbeHandler(CncaHandler):
    """只确认极验被唤起，不等人工。"""

    def wait_geetest(self, page, what: str, timeout: int = 300) -> None:
        self.inject_geetest_hook(page)
        deadline = time.time() + 40
        while time.time() < deadline:
            self.engine.check_stop()
            n = self.geetest_asked(page)
            if n:
                self.engine.log("  ✔ 极验已被唤起（showCaptcha 调用 %d 次）：%s"
                                % (n, what))
                shot = os.path.join(OUT, "geetest.png")
                try:
                    page.screenshot(path=shot)
                    self.engine.log("    截图：%s" % shot)
                except Exception:
                    pass
                return
            self.engine.sleep(0.5)
        raise EngineError("等了 40 秒没等到极验被唤起（%s）" % what)


def main():
    os.makedirs(OUT, exist_ok=True)
    eng = Engine(output_dir=OUT, browser="Edge", shot_mode="raw", log=print)
    h = ProbeHandler(eng)
    fails = []
    try:
        pw, browser, ctx, page = eng.open_browser()
        print("浏览器已就绪")
        h.search(page, COMPANY)
        print("\n✔ 全链路走到极验弹层，验证通过")
    except Exception as exc:
        fails.append(str(exc))
        print("\n✘ 验证失败：%s" % str(exc).splitlines()[0])
    finally:
        try:
            eng.close_browser()
        except Exception:
            pass

    if fails:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
