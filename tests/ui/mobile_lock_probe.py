import sys, json
from playwright.sync_api import sync_playwright
url = sys.argv[1]; shot = sys.argv[2] if len(sys.argv) > 2 else ""
JS = """() => {
  const vw = innerWidth, out=[];
  for (const e of document.querySelectorAll('body *')) { const r=e.getBoundingClientRect(); const cs=getComputedStyle(e);
    if (cs.display!=='none' && r.width>0 && r.right>vw+1 && !e.closest('#side')) out.push((e.id||e.className||e.tagName).toString().slice(0,30)+' '+Math.round(r.left)+'..'+Math.round(r.right)); }
  const scrollers=[...document.querySelectorAll('*')].filter(e=>e.scrollWidth>e.clientWidth+1 && /(auto|scroll)/.test(getComputedStyle(e).overflowX)).map(e=>(e.id||e.className||e.tagName).toString().slice(0,30)+' sw='+e.scrollWidth+' cw='+e.clientWidth);
  const hdr=document.querySelector('header'), comp=document.querySelector('#composer');
  const log=document.querySelector('#log'); return {msgs: log && log.children.length, logScroll: log && (log.scrollHeight+'/'+log.clientHeight), vw, sw: document.documentElement.scrollWidth, sh: document.documentElement.scrollHeight, vh: innerHeight, sx: scrollX, sy: scrollY,
    hdr: hdr && Math.round(hdr.getBoundingClientRect().top), comp: comp && Math.round(comp.getBoundingClientRect().bottom),
    htmlOB: getComputedStyle(document.documentElement).overscrollBehavior, bodyCls: document.body.className, over: out.slice(0,12), hscroll: scrollers.slice(0,10)}; }"""
with sync_playwright() as p:
    b = p.chromium.launch()
    for w,h in [(360,780),(412,915)]:
        pg = b.new_page(viewport={"width":w,"height":h}, is_mobile=True, has_touch=True, device_scale_factor=2)
        pg.add_init_script("localStorage.session='demo'")
        pg.goto(url); pg.wait_for_timeout(2000)
        pg.evaluate("""() => { document.documentElement.classList.remove('auth-boot'); const g=document.querySelector('#auth-gate'); if (g) g.hidden=true; }""")
        pg.evaluate("""() => { if (window.openSession) window.openSession('demo'); }""")
        pg.wait_for_timeout(1500)
        pg.evaluate("""() => { for (let i=0;i<10;i++){ addUser('message '+i+' supercalifragilisticexpialidocious_supercalifragilistic_word_'+i);
          const b=addBot(); b.row.querySelector('.md').innerHTML = '<p>Link https://example.com/'+'a'.repeat(180)+'</p><pre><code>x = "'+'y'.repeat(200)+'"</code></pre><table><tr>'+'<td>wide cell text here</td>'.repeat(8)+'</tr></table><img src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%221400%22 height=%22300%22/%3E">'; } }""")
        pg.wait_for_timeout(800)
        before = pg.evaluate(JS)
        pg.evaluate("() => { window.scrollTo(300,300); document.documentElement.scrollLeft=300; document.body.scrollLeft=300; const l=document.querySelector('#log'); if(l) l.scrollLeft=300; }")
        after = pg.evaluate("() => ({sx: scrollX, sy: scrollY, bl: document.body.scrollLeft, logL: (document.querySelector('#log')||{}).scrollLeft, mainL: (document.querySelector('main')||{}).scrollLeft})")
        print(w, json.dumps(before)); print('  after-push', json.dumps(after))
        if shot: pg.screenshot(path=f"{shot}-{w}.png")
        # keyboard: tap the composer and shrink the viewport like an Android keyboard does
        pg.click('#composer textarea', timeout=3000)
        pg.set_viewport_size({"width": w, "height": h - 320}); pg.wait_for_timeout(600)
        k = pg.evaluate(JS); print('  keyboard', json.dumps({x: k[x] for x in ('vw','sw','vh','sx','sy','hdr','comp')}))
        if shot: pg.screenshot(path=f"{shot}-{w}-kb.png")
    b.close()
