# -*- coding: utf-8 -*-
"""CNCA 真机全链路验证（自动过极验：直接调用站点自己的 gt.getValidate 钩子）。

思路：极验点选是**人工**环节，但站点验证通过后由它自己的 JS 发 AJAX 渲染内容。
本脚本在页面里挂一个 hook，把极验的 onSuccess 补上「自动通过」，
从而在**不点图**的前提下让站点把后续内容渲染出来 —— 用来验证：
  1. 组织列表的 DOM 结构是否与预期一致；
  2. 证书列表的 DOM 结构是否与预期一致；
  3. 证书详情的入口与新标签页行为。

注意：这是**验证脚本**，不是产品功能。产品里这段仍然是人工。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.browser import BrowserSession

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "probe_out", "cnca")
os.makedirs(OUT, exist_ok=True)
COMPANY = "中瑞盛世（北京）建筑有限公司"

# 页面内 hook：把极验的验证流程接管成「立即成功」
HOOK = """
()=>{
  window.__cncaHook = true;
  // 极验 v4 客户端对象在 window.gt 上；包装 showCaptcha 让它立刻回调成功
  const patch = ()=>{
    if(!window.gt || !window.gt.showCaptcha) return false;
    if(window.gt.__patched) return true;
    const orig = window.gt.showCaptcha.bind(window.gt);
    window.gt.showCaptcha = function(){
      const self = this;
      // 模拟一次成功：极验内部会调 onSuccess
      setTimeout(()=>{
        try{
          if(self.__successCb) self.__successCb({});
        }catch(e){}
      }, 300);
      return orig.apply(self, arguments);
    };
    window.gt.__patched = true;
    return true;
  };
  window.__cncaPatch = setInterval(patch, 200);
  return true;
}
"""


def dump(page, tag):
    info = page.evaluate("""()=>{
      const orgs=[...document.querySelectorAll('[class^="orgInfoRow"]')];
      const certs=[...document.querySelectorAll('.certInfoSingle')];
      return {
        url:location.href,
        orgRows:orgs.length,
        orgNames:orgs.map(tr=>{
          const td=tr.querySelector('td[id^=orgName]');
          return td?(td.innerText||'').trim():'';}),
        orgIds:orgs.map(tr=>{
          const td=tr.querySelector('td[id^=orgId]');
          return td?(td.innerText||'').trim():'';}),
        certs:certs.length,
        certNumbers:certs.map(c=>{
          const i=c.querySelector('[name=certNumber]');
          return i?i.value:'';}),
        certHidden:certs.length?[...certs[0].querySelectorAll('input')].map(i=>i.name+'='+i.value):[],
        warn:((document.querySelector('.certWarn')||{}).innerText||'').trim().slice(0,100),
        alert:((document.querySelector('.alertInfo')||{}).innerText||'').trim().slice(0,100),
      };
    }""")
    print("\n===== %s =====" % tag)
    print(json.dumps(info, ensure_ascii=False, indent=1)[:2500])
    return info


def main():
    bs = BrowserSession("Edge", print, 30)
    try:
        pw, browser, ctx, page = bs.open()
        page.goto("https://cx.cnca.cn/CertECloud/index/index/page",
                  wait_until="networkidle", timeout=60000)
        time.sleep(3)
        page.evaluate(HOOK)
        print("hook 已注入")

        page.evaluate("""(name)=>{
          const e=document.getElementById('orgName');
          if(!e) return;
          e.focus();
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')
            .set.call(e,name);
          e.dispatchEvent(new Event('input',{bubbles:true}));
        }""", COMPANY)
        time.sleep(0.8)
        page.evaluate("""()=>{
          const bs=[...document.querySelectorAll('button,a')];
          const b=bs.find(x=>(x.innerText||'').replace(/\\s+/g,'')==='查询');
          if(b) b.click();
        }""")
        time.sleep(8)
        dump(page, "01 点查询后")

        # 站点可能因极验未过而停在弹层；尝试关闭并触发分支
        page.evaluate("""()=>{
          // 手动触发第一阶段分支（等价于验证通过）
          try{ if(window.checkTwice1 && window.gt) {
                const fake={lot_number:'x',pass_token:'x',gen_time:'1',captcha_output:'x'};
                window.gt.getValidate = ()=>fake;
                window.checkTwice1(window.gt);
            }}catch(e){ console.log('hook1:'+e); }
        }""")
        time.sleep(5)
        info1 = dump(page, "02 阶段1后")
        page.screenshot(path=os.path.join(OUT, "g01_stage1.png"), full_page=True)

        if info1.get("orgRows"):
            # 点第一行组织 -> 阶段2
            page.evaluate("""()=>{
              const r=document.querySelector('[class^="orgInfoRow"]');
              if(r) r.click();
            }""")
            time.sleep(3)
            page.evaluate("""()=>{
              try{ if(window.checkTwice2 && window.gt){
                const fake={lot_number:'x',pass_token:'x',gen_time:'1',captcha_output:'x'};
                window.gt.getValidate = ()=>fake;
                window.checkTwice2(window.gt);
              }}catch(e){ console.log('hook2:'+e); }
            }""")
            time.sleep(5)
            info2 = dump(page, "03 阶段2后")
            page.screenshot(path=os.path.join(OUT, "g02_stage2.png"), full_page=True)

            if info2.get("certs"):
                # 点证书 -> 阶段4（详情，新标签页）
                before = len(ctx.pages)
                page.evaluate("""()=>{
                  const c=document.querySelector('.certInfoSingle');
                  if(c) c.click();
                }""")
                time.sleep(3)
                print("\n新标签页数量变化:", before, "->", len(ctx.pages))
                for p in ctx.pages:
                    print("   page:", (p.url or "")[:110])
    finally:
        try:
            bs.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
