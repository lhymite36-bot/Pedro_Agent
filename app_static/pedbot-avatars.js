/* Ped Bot avatar engine — original implementation (no third-party code or data).
   Procedural SVG, rAF loop, bezier keyframe clips + spring physics, pseudo-3D
   eyes on a sphere, soft radial shading, ground shadow, cursor follow, poke, drag.
   Usage: const bot = PedBot.create(el, {shape:'ball', size:160, state:'idle', follow:true});
          bot.setState('working'|'thinking'|'happy'|'sleepy'|...); bot.poke(); */
(function(){
const NS='http://www.w3.org/2000/svg';
const E=(x,y,w,h,r=0)=>({x,y,w,h,r});
// Body = list of primitives (p: path d, c: circle, rr: rounded rect), optional stroke width / group rotation.
// Outlines are sampled into radial profiles r(θ) at startup so every shape can morph into every other.
const SHAPES={
 drop:{color:'#7a7a7a',prims:[{p:'M100,24 C128,56 170,86 170,128 C170,166 138,182 100,182 C62,182 30,166 30,128 C30,86 72,56 100,24Z'}],c:[100,128],eyes:[E(84,120,15,32),E(114,120,15,32)]},
 triangle:{color:'#1683f5',prims:[{p:'M100,48 L162,160 L38,160Z',sw:40}],c:[100,128],eyes:[E(89,136,11,24),E(113,136,11,24)]},
 cloud:{color:'#ff6a00',prims:[{c:[70,115,44]},{c:[108,82,42]},{c:[140,112,40]},{c:[96,140,40]},{c:[142,145,30]},{c:[58,148,28]}],c:[100,118],eyes:[E(90,100,30,11,22),E(132,114,30,11,22)]},
 ball:{color:'#0b0b0d',prims:[{c:[100,110,72]}],c:[100,110],eyes:[E(80,88,12,26,30),E(108,82,12,26,30)]},
 pill:{color:'#00c473',prims:[{rr:[22,58,156,108,54]}],c:[100,112],eyes:[E(80,108,20,38),E(120,108,20,38)]},
 clover:{color:'#8b5a32',rot:-12,prims:[{c:[72,78,38]},{c:[130,80,38]},{c:[70,140,38]},{c:[132,140,38]},{rr:[62,72,80,78,0]}],c:[100,110],eyes:[E(94,118,11,28,25),E(122,110,11,28,25)]},
 circle:{color:'#ec4899',prims:[{c:[100,112,66]}],c:[100,112]},
 square:{color:'#14b8a6',prims:[{rr:[40,52,120,120,34]}],c:[100,112]},
 hexagon:{color:'#8b5cf6',prims:[{p:'M100,58 L148,86 L148,140 L100,168 L52,140 L52,86Z',sw:22}],c:[100,113]},
 star:{color:'#f5b301',prims:[{p:'M100,44 L118,92 L168,94 L128,124 L142,172 L100,144 L58,172 L72,124 L32,94 L82,92Z',sw:16}],c:[100,114]},
 pedbot:{color:'#f2f2f2',eye:'#0b0b0d',prims:[{c:[100,110,72]}],c:[100,110],eyes:[E(84,104,15,36),E(116,104,15,36)]},   // 1.4.17: Ped Bot himself - white 3D ball, black pill eyes
 heart:{color:'#e8344e',prims:[{p:'M100,176 C60,146 28,120 28,88 C28,62 48,46 70,46 C84,46 94,54 100,66 C106,54 116,46 130,46 C152,46 172,62 172,88 C172,120 140,146 100,176Z'}],c:[100,108]},
};
const EYE_SCALE=1.28, N=96;
function buildProfiles(){const cv=document.createElement('canvas').getContext('2d');
 for(const k in SHAPES){const S=SHAPES[k];const paths=S.prims.map(q=>{const P=new Path2D();
   if(q.p)P.addPath(new Path2D(q.p));if(q.c)P.arc(q.c[0],q.c[1],q.c[2],0,7);if(q.rr){const[x,y,w,h,r]=q.rr;P.roundRect?P.roundRect(x,y,w,h,r):P.rect(x,y,w,h)}return{P,sw:q.sw}});
  const a=(S.rot||0)*Math.PI/180,inside=(x,y)=>{const rx=100+(x-100)*Math.cos(-a)-(y-110)*Math.sin(-a),ry=110+(x-100)*Math.sin(-a)+(y-110)*Math.cos(-a);
   return paths.some(({P,sw})=>{if(cv.isPointInPath(P,rx,ry))return true;if(sw){cv.lineWidth=sw;cv.lineJoin='round';return cv.isPointInStroke(P,rx,ry)}return false})};
  const[cx,cy]=S.c;S.r=[];for(let i=0;i<N;i++){const t=i/N*2*Math.PI,dx=Math.cos(t),dy=Math.sin(t);let r=130;while(r>1&&!inside(cx+dx*r,cy+dy*r))r-=.5;S.r.push(r)}
  S.R=S.r.reduce((x,y)=>x+y)/N*1.02;S.gy=cy+Math.max(...S.r.map((r,i)=>r*Math.sin(i/N*2*Math.PI)));
  if(!S.eyes){S.eyes=[E(cx-15,cy-4,14,30),E(cx+15,cy-4,14,30)]}}}
// ---- color helpers
const hex=h=>[1,3,5].map(i=>parseInt(h.substr(i,2),16)/255);
const toHex=c=>'#'+c.map(v=>Math.round(Math.max(0,Math.min(1,v))*255).toString(16).padStart(2,'0')).join('');
const mix=(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t);
// ---- cubic bezier easing (Newton solve x(t), return y; y may overshoot)
function bez(p,x){const[a,b,c,d]=p;const cx=3*a,bx=3*(c-a)-cx,ax=1-cx-bx,cy=3*b,by=3*(d-b)-cy,ay=1-cy-by;
 let t=x;for(let i=0;i<8;i++){const f=((ax*t+bx)*t+cx)*t-x,df=(3*ax*t+2*bx)*t+cx;if(Math.abs(f)<1e-5||!df)break;t-=f/df;}
 t=Math.max(0,Math.min(1,t));return((ay*t+by)*t+cy)*t;}
const EASE={io:[.42,0,.58,1],out:[.2,.8,.3,1],soft:[.87,-.08,.3,1.02],back:[.5,-.35,.3,1.35],pop:[.3,1.6,.5,1],drop:[.6,0,.9,.6],rise:[.1,.4,.4,1]};
// ---- clips: channel -> [[t,value,ease],...] ; eases apply from that key to the next
const C=(dur,tracks,extra={})=>({dur,tracks,...extra});
const CLIPS={
 idle_breathe:C(4,{sy:[[0,1,'soft'],[1.6,.965,'soft'],[3.4,1.01,'io'],[4,1]],sx:[[0,1,'soft'],[1.6,1.03,'soft'],[3.4,.995,'io'],[4,1]],pitch:[[0,0,'io'],[2,-5,'io'],[4,0]]},{blinks:[1.4]}),
 idle_glance:C(6,{yaw:[[0,0,'soft'],[.7,-22,'io'],[2.2,-22,'soft'],[2.9,20,'io'],[4.3,20,'soft'],[5.1,0]],pitch:[[0,0,'io'],[.7,4,'io'],[2.9,-6,'io'],[5.1,0]],roll:[[0,0,'io'],[.7,-4,'io'],[2.9,4,'io'],[5.1,0]]},{blinks:[2.5,4.75,5.05]}),
 idle_bob:C(4,{y:[[0,0,'io'],[1,-6,'io'],[2,0,'io'],[3,-6,'io'],[4,0]],sy:[[0,1,'io'],[2,.97,'back'],[2.4,1]],roll:[[0,0,'io'],[2,6,'soft'],[4,0]]},{blinks:[3.1]}),
 roll:C(3,{x:[[0,-60,'io'],[1.5,60,'io'],[3,-60]],sx:[[0,1.08,'out'],[.25,1],[1.25,1,'out'],[1.5,1.08,'out'],[1.75,1],[2.75,1,'out'],[3,1.08]],sy:[[0,.92,'out'],[.25,1],[1.25,1,'out'],[1.5,.92,'out'],[1.75,1],[2.75,1,'out'],[3,.92]]},{rollFromX:true}),
 spin:C(1.6,{rot:[[0,0,'back'],[1.1,360],[1.6,360]],sy:[[0,1,'io'],[.15,.88,'io'],[.5,1.06,'io'],[1.1,1,'pop'],[1.25,.9,'io'],[1.6,1]],sx:[[0,1,'io'],[.15,1.1,'io'],[.5,.95,'io'],[1.1,1,'pop'],[1.25,1.1,'io'],[1.6,1]],yaw:[[0,0,'io'],[.5,25,'io'],[1.1,0]]},{center:true}),
 bounce:C(1,{y:[[0,0,'rise'],[.5,-70,'drop'],[1,0]],sy:[[0,.8,'out'],[.12,1.1,'io'],[.5,1,'io'],[.9,1.08,'io'],[1,.8]],sx:[[0,1.2,'out'],[.12,.92,'io'],[.5,1,'io'],[.9,.94,'io'],[1,1.2]],pitch:[[0,8,'io'],[.5,-8,'io'],[1,8]]}),
 wobble:C(1.4,{sx:[[0,1,'io'],[.15,1.16,'io'],[.35,.88,'io'],[.55,1.08,'io'],[.75,.95,'io'],[1,1.02,'io'],[1.4,1]],sy:[[0,1,'io'],[.15,.86,'io'],[.35,1.12,'io'],[.55,.94,'io'],[.75,1.04,'io'],[1,.99,'io'],[1.4,1]],skew:[[0,0,'io'],[.15,7,'io'],[.35,-6,'io'],[.55,4,'io'],[.75,-2,'io'],[1.4,0]]}),
 hop:C(.8,{y:[[0,0,'rise'],[.35,-32,'drop'],[.7,0],[.8,0]],roll:[[0,0,'io'],[.35,-8,'io'],[.7,0]],sy:[[0,.9,'out'],[.1,1.06,'io'],[.65,1,'io'],[.72,.9,'out'],[.8,1]],sx:[[0,1.1,'out'],[.1,.95,'io'],[.65,1,'io'],[.72,1.1,'out'],[.8,1]]}),
 look:C(3,{yaw:[[0,0,'soft'],[.5,-26,'io'],[1.2,-26,'soft'],[1.7,26,'io'],[2.4,26,'soft'],[2.9,0]],pitch:[[0,0,'io'],[1.7,-10,'io'],[2.9,0]]},{blinks:[1.45]}),
 happy:C(1.7,{y:[[0,0,'io'],[.25,6,'rise'],[.7,-80,'drop'],[1.15,0],[1.7,0]],rot:[[0,0,'io'],[.3,0,'io'],[1.1,360],[1.7,360]],sy:[[0,1,'io'],[.25,.78,'out'],[.4,1.12,'io'],[1.1,1,'out'],[1.2,.82,'pop'],[1.45,1],[1.7,1]],sx:[[0,1,'io'],[.25,1.2,'out'],[.4,.92,'io'],[1.1,1,'out'],[1.2,1.18,'pop'],[1.45,1],[1.7,1]]},{center:true,face:'happy'}),
 sleepy:C(4,{sy:[[0,1,'io'],[2,.9,'io'],[4,1]],sx:[[0,1,'io'],[2,1.06,'io'],[4,1]],pitch:[[0,4,'io'],[2,14,'io'],[4,4]],roll:[[0,-4,'io'],[2,6,'io'],[4,-4]]},{face:'sleepy'}),
 thinking:C(2.4,{yaw:[[0,14,'io'],[1.2,20,'io'],[2.4,14]],pitch:[[0,-14,'io'],[1.2,-18,'io'],[2.4,-14]],sy:[[0,1,'io'],[1.2,1.03,'io'],[2.4,1]]},{deco:'orbit',shrink:.72}),
 working:C(3,{x:[[0,-40,'io'],[1.5,40,'io'],[3,-40]],y:[[0,0,'io'],[.75,-4,'io'],[1.5,0,'io'],[2.25,-4,'io'],[3,0]]},{rollFromX:true,deco:'spark'}),
};
const STATES={idle:['idle_breathe','idle_glance','idle_breathe','idle_bob'],roll:['roll'],spin:['spin'],bounce:['bounce'],wobble:['wobble'],hop:['hop'],look:['look'],happy:['happy'],done:['happy'],sleepy:['sleepy'],thinking:['thinking'],working:['working','spin'],blinking:['idle_breathe']};
const NEXT={done:'idle'};
const CH=['x','y','rot','sx','sy','skew','yaw','pitch','roll'];
const DEF={x:0,y:0,rot:0,sx:1,sy:1,skew:0,yaw:0,pitch:0,roll:0};
function sample(clip,t){const o={};for(const k of CH){const tr=clip.tracks[k];if(!tr){o[k]=DEF[k];continue}
 if(t<=tr[0][0]){o[k]=tr[0][1];continue}let v=tr[tr.length-1][1];
 for(let i=0;i<tr.length-1;i++){const a=tr[i],b=tr[i+1];if(t>=a[0]&&t<=b[0]){const u=(t-a[0])/(b[0]-a[0]||1);v=a[1]+(b[1]-a[1])*bez(EASE[a[2]||'io'],u);break}}o[k]=v}
 if(clip.rollFromX)o.rot=o.x/ (clip._R||70)*57.2958; return o}
// ---- spring (semi-implicit Euler, 120 Hz substeps)
class Spring{constructor(w,z,x=0){this.w=w;this.z=z;this.x=x;this.v=0;this.t=x}
 step(dt){const h=1/120;for(let s=dt;s>1e-6;s-=h){const d=Math.min(h,s);this.v+=(-2*this.z*this.w*this.v-this.w*this.w*(this.x-this.t))*d;this.x+=this.v*d}return this.x}}
function rng(seed){let s=seed>>>0||1;return()=>((s=(s*1664525+1013904223)>>>0)/4294967296)}
function el(tag,a={},p){const e=document.createElementNS(NS,tag);for(const k in a)e.setAttribute(k,a[k]);p&&p.appendChild(e);return e}
let UID=0;const BOTS=[];let built=false;
const REDUCED=typeof matchMedia!=='undefined'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
const STATE_SHAPE={done:'star',love:'heart'};
CLIPS.love=C(4,{...CLIPS.idle_bob.tracks},{face:'happy',blinks:[]});CLIPS.happy.face='happy';STATES.love=['love'];
function smoothPath(pts){let d='';const n=pts.length;for(let i=0;i<n;i++){const p0=pts[(i-1+n)%n],p1=pts[i],p2=pts[(i+1)%n],p3=pts[(i+2)%n];
 if(!i)d+=`M${p1[0].toFixed(2)},${p1[1].toFixed(2)}`;d+=`C${(p1[0]+(p2[0]-p0[0])/6).toFixed(2)},${(p1[1]+(p2[1]-p0[1])/6).toFixed(2)} ${(p2[0]-(p3[0]-p1[0])/6).toFixed(2)},${(p2[1]-(p3[1]-p1[1])/6).toFixed(2)} ${p2[0].toFixed(2)},${p2[1].toFixed(2)}`}return d+'Z'}
function snapshotShape(k,color){const S=SHAPES[k];return{r:S.r.slice(),c:S.c.slice(),gy:S.gy,R:S.R,col:hex(/^#[0-9a-fA-F]{6}$/.test(color||'')?color:S.color),eyes:S.eyes.map(e=>({...e}))}}
function lerpShape(A,B,w){const L=(x,y)=>x+(y-x)*w;return{r:A.r.map((v,i)=>L(v,B.r[i])),c:[L(A.c[0],B.c[0]),L(A.c[1],B.c[1])],gy:L(A.gy,B.gy),R:L(A.R,B.R),col:A.col.map((v,i)=>L(v,B.col[i])),
 eyes:A.eyes.map((e,i)=>{const f=B.eyes[i];return{x:L(e.x,f.x),y:L(e.y,f.y),w:L(e.w,f.w),h:L(e.h,f.h),r:L(e.r,f.r)}})}}
function create(host,o={}){
 if(!built){buildProfiles();built=true}
 const id='pb'+(UID++),size=o.size||160;
 const fit=o.fit!==false&&!o.size;const svg=el('svg',fit?{viewBox:'0 0 200 230',width:'100%',height:'100%',preserveAspectRatio:'xMidYMid meet',style:'overflow:visible;touch-action:none;display:block'}:{viewBox:'0 0 200 230',width:size,height:size*1.15,style:'overflow:visible;touch-action:none;cursor:grab'});
 const defs=el('defs',{},svg);
 const g=el('radialGradient',{id:id+'g',gradientUnits:'userSpaceOnUse'},defs);const stops=[0,.42,1].map(of=>el('stop',{offset:of},g));
 const sg=el('radialGradient',{id:id+'s'},defs);el('stop',{offset:0,'stop-color':'#000','stop-opacity':.16},sg);el('stop',{offset:1,'stop-color':'#000','stop-opacity':0},sg);
 const shadow=el('ellipse',{cx:100,cy:200,rx:62,ry:11,fill:`url(#${id}s)`},svg);
 const gPos=el('g',{},svg),gSq=el('g',{},gPos),gRot=el('g',{},gSq);
 const body=el('path',{fill:`url(#${id}g)`},gRot);const sideDots=[0,1].map(()=>el('circle',{r:0,fill:`url(#${id}g)`},gPos));
 const spec=el('ellipse',{fill:'#fff'},gRot);
 const eyesG=el('g',{fill:'#fff'},gRot);const eyes=[0,1].map(()=>el('rect',{},eyesG));
 const arcs=[0,1].map(()=>el('path',{fill:'none',stroke:'#fff','stroke-linecap':'round'},gRot));
 const sparkG=el('g',{fill:'#e8ecf3'},svg);const sparks=[0,1,2].map(()=>el('circle',{r:0},sparkG));
 host.appendChild(svg);
 const r=rng(o.seed||UID*7919);
 const base=SHAPES[o.shape]?o.shape:'ball';const color0=o.color||'';
 const B={state:o.state||'idle',clip:null,ct:0,from:null,bridge:1,base,shape:base,visible:true,
  gyaw:new Spring(9,.55),gpitch:new Spring(9,.55),pokeS:new Spring(16,.25,0),morph:new Spring(9,.78,1),think:new Spring(10,.8,0),happyA:new Spring(14,.85,0),spark:new Spring(14,.9,0),
  color:color0,mFrom:snapshotShape(base,color0),mTo:snapshotShape(base,color0),cur:snapshotShape(base,color0),blinkT:-9,follow:!!o.follow,drag:null,last:sample(CLIPS.idle_breathe,0),time:0};
 B.morph.t=1;
 function pick(){const l=STATES[B.state]||STATES.idle;B.clip=CLIPS[l[Math.floor(r()*l.length)]];B.ct=0;}
 function setShape(k){if(!SHAPES[k]||k===B.shape)return;B.shape=k;B.mFrom=JSON.parse(JSON.stringify(B.cur));B.mTo=snapshotShape(k,B.color);B.morph.x=0;B.morph.v=0;B.morph.t=1}
 function setState(s){wake(B,4000);B.from={...B.last};B.bridge=0;B.state=s;pick();setShape(STATE_SHAPE[s]||B.base)}
 function blink(){B.blinkT=0}
 function poke(){wake(B,3000);B.pokeS.v-=6;blink()}
 pick();
 svg.addEventListener('pointerdown',e=>{B.drag={x:e.clientX,y:e.clientY,yaw:B.gyaw.x,pitch:B.gpitch.x,moved:0};svg.setPointerCapture(e.pointerId);svg.style.cursor='grabbing'});
 svg.addEventListener('pointermove',e=>{if(!B.drag)return;const dx=e.clientX-B.drag.x,dy=e.clientY-B.drag.y;B.drag.moved=Math.max(B.drag.moved,Math.hypot(dx,dy));B.gyaw.t=Math.max(-60,Math.min(60,B.drag.yaw+dx*.6));B.gpitch.t=Math.max(-40,Math.min(40,B.drag.pitch-dy*.6))});
 svg.addEventListener('pointerup',()=>{if(B.drag&&B.drag.moved<4)poke();B.drag=null;svg.style.cursor='grab';B.pokeS.v-=3});
 B.look=(px,py)=>{if(B.drag||!B.follow)return;const bb=svg.getBoundingClientRect();const dx=(px-(bb.left+bb.width/2))/innerWidth,dy=(py-(bb.top+bb.height/2))/innerHeight;
  B.gyaw.t=Math.max(-28,Math.min(28,dx*70));B.gpitch.t=Math.max(-18,Math.min(18,-dy*50))};
 if(typeof IntersectionObserver!=='undefined')new IntersectionObserver(es=>es.forEach(e=>B.visible=e.isIntersecting)).observe(svg);
 B.update=dt=>{
  const springs=[B.gyaw,B.gpitch,B.pokeS,B.morph,B.think,B.happyA,B.spark];
  if(REDUCED){dt=0;B.ct=0}
  B.time+=dt;B.ct+=dt;
  if(B.ct>=B.clip.dur){if(NEXT[B.state]){setState(NEXT[B.state])}else{B.ct-=B.clip.dur;const prev=B.clip;pick();if(B.clip!==prev){B.from={...B.last};B.bridge=0}}}
  let p=sample(B.clip,B.ct);
  if(B.bridge<1){B.bridge=REDUCED?1:Math.min(1,B.bridge+dt/.35);const w=bez(EASE.out,B.bridge);for(const k of CH)p[k]=B.from[k]+(p[k]-B.from[k])*w}
  B.last=p;
  for(const bt of B.clip.blinks||[])if(B.ct-dt<bt&&B.ct>=bt)blink();
  B.blinkT+=dt;const bt=B.blinkT/.26;let lid=1;if(bt<1)lid=bt<.45?1-bez(EASE.io,bt/.45):bez(EASE.io,(bt-.45)/.55)*1.06;lid=Math.min(1,lid)||.06;
  const face=B.clip.face;if(face==='sleepy')lid=Math.min(lid,.16);
  B.think.t=B.clip.deco==='orbit'?1:0;B.happyA.t=face==='happy'?1:0;B.spark.t=B.clip.deco==='spark'?1:0;
  if(REDUCED)springs.forEach(s=>{s.x=s.t;s.v=0});
  const gyv=B.gyaw.step(dt),gpv=B.gpitch.step(dt),pk=B.pokeS.step(dt),mw=B.morph.step(dt),th=Math.max(0,Math.min(1,B.think.step(dt))),ha=Math.max(0,Math.min(1,B.happyA.step(dt))),sp=B.spark.step(dt);
  // shape morph (spring weight may overshoot slightly -> jelly)
  const M=B.cur=lerpShape(B.mFrom,B.mTo,mw);const R=M.R,[cx,cy]=M.c;
  const ec=(SHAPES[B.shape]||{}).eye||'#fff';if(ec!==B._ec){B._ec=ec;eyesG.setAttribute('fill',ec);arcs.forEach(q=>q.setAttribute('stroke',ec))}
  const isDark=M.col.reduce((a,b)=>a+b)<.3,col=mix(M.col,[1,1,1],isDark?.32*B.think.x:0);
  [mix(col,[1,1,1],isDark?.06:.08),col,mix(col,[0,0,0],isDark?.16:.12)].forEach((c,i)=>stops[i].setAttribute('stop-color',toHex(c)));
  // thinking: body collapses into the middle of three dots
  const dotR=15,ease=bez(EASE.io,th),bob=k=>-9*Math.max(0,Math.sin(B.time*6-k*1.1))*th;
  const pts=M.r.map((rv,i)=>{const t=i/N*2*Math.PI,rr=rv+(dotR-rv)*ease;return[cx+Math.cos(t)*rr,cy-(cy-(M.gy-dotR))*ease+Math.sin(t)*rr+bob(1)]});
  body.setAttribute('d',smoothPath(pts));
  const yaw=p.yaw+gyv,pitch=p.pitch+gpv,roll=p.roll;
  const sx=p.sx*(1-pk*.12),sy=p.sy*(1+pk*.15);
  const ox=100-cx,oy=190-M.gy;const ay=B.clip.center?cy:M.gy;
  gPos.setAttribute('transform',`translate(${ox+p.x} ${oy+p.y})`);
  gSq.setAttribute('transform',`translate(${cx} ${ay}) skewX(${p.skew}) scale(${sx} ${sy}) translate(${-cx} ${-ay})`);
  gRot.setAttribute('transform',`rotate(${p.rot+roll} ${cx} ${cy})`);
  sideDots.forEach((d,k)=>{const s=k?1:-1,e2=bez(EASE.out,Math.max(0,(th-.25)/.75));d.setAttribute('cx',cx+s*40*e2);d.setAttribute('cy',M.gy-dotR+bob(k?2:0));d.setAttribute('r',dotR*e2)});
  const lx=cx-R*.38*(1-th)-yaw*.9,ly=cy+(M.gy-dotR-cy)*th-R*.42*(1-th)+pitch*.9;
  g.setAttribute('cx',lx);g.setAttribute('cy',ly);g.setAttribute('fx',lx);g.setAttribute('fy',ly);g.setAttribute('r',R*1.55*(1-th*.35));
  spec.setAttribute('cx',lx+R*.05);spec.setAttribute('cy',ly-R*.02);spec.setAttribute('rx',R*.26);spec.setAttribute('ry',R*.14);spec.setAttribute('transform',`rotate(-30 ${lx} ${ly})`);
  spec.setAttribute('opacity',0);
  const Y=yaw*Math.PI/180,P=pitch*Math.PI/180,eyeOn=Math.max(0,1-th*2.2);
  M.eyes.forEach((e,i)=>{let vx=(e.x-cx)/R,vy=(e.y-cy)/R,vz=Math.sqrt(Math.max(.05,1-vx*vx-vy*vy));
   let x1=vx*Math.cos(Y)+vz*Math.sin(Y),z1=-vx*Math.sin(Y)+vz*Math.cos(Y);
   let y2=vy*Math.cos(P)-z1*Math.sin(P),z2=vy*Math.sin(P)+z1*Math.cos(P);
   const vis=Math.max(0,Math.min(1,z2*4))*eyeOn,fx=Math.max(.15,Math.sqrt(Math.max(0,1-x1*x1))/Math.sqrt(Math.max(.05,1-vx*vx))),fy=Math.max(.15,Math.sqrt(Math.max(0,1-y2*y2))/Math.sqrt(Math.max(.05,1-vy*vy)));
   const ex=cx+x1*R,ey=cy+y2*R;const w=e.w*EYE_SCALE*fx,h=e.h*EYE_SCALE*fy*lid;
   const a=eyes[i];a.setAttribute('x',ex-w/2);a.setAttribute('y',ey-h/2);a.setAttribute('width',w);a.setAttribute('height',Math.max(h,2));a.setAttribute('rx',Math.min(w,h)/2);
   a.setAttribute('transform',`rotate(${e.r*(1-ha)} ${ex} ${ey})`);a.setAttribute('opacity',vis*(1-ha));
   // '^^' happy arch eye: grows out of the pill
   const gap=Math.abs(M.eyes[1].x-M.eyes[0].x)||30,big=Math.max(e.w,e.h)*EYE_SCALE,hw=Math.min(big*.36,gap*.34)*fx,hh=hw*.75,sw=Math.min(8,Math.min(e.w,e.h)*EYE_SCALE*.55);
   const q=arcs[i];q.setAttribute('d',`M${ex-hw},${ey+hh*.5} Q${ex},${ey-hh*2} ${ex+hw},${ey+hh*.5}`);q.setAttribute('stroke-width',sw*(.6+.4*ha));q.setAttribute('opacity',vis*ha)});
  const lift=Math.max(0,-p.y)/90;shadow.setAttribute('rx',62*(R/72)*(1-th*.1)*(1-lift*.45)*(.8+.2*p.sx));shadow.setAttribute('cx',100+p.x);shadow.setAttribute('opacity',1-lift*.6);
  sparks.forEach((d,k)=>{const ang=B.time*3+k*2.094,rr=R*1.05;d.setAttribute('cx',100+p.x+Math.cos(ang)*rr);d.setAttribute('cy',190-(M.gy-cy)+p.y+Math.sin(ang)*rr*.35-R*.2);d.setAttribute('r',sp*(4+2*Math.sin(B.time*8+k)));d.setAttribute('opacity',sp*(Math.sin(ang)>-.2?1:.45))});
 };
 B.svg=svg;B.host=host;B.setColor=c=>{B.color=c||'';B.mFrom=JSON.parse(JSON.stringify(B.cur));B.mTo=snapshotShape(B.shape,B.color);B.morph.x=0;B.morph.v=0;B.morph.t=1};B.destroy=()=>{const i=BOTS.indexOf(B);if(i>=0)BOTS.splice(i,1);svg.remove()};B.setState=setState;B.morphTo=setShape;B.setShape=k=>{B.base=k;setShape(k)};B.blink=blink;B.poke=poke;B.big=!!o.follow||(o.size||0)>=80;BOTS.push(B);B.update(0);return B;}
let lastT=null,manual=false;
// 1.4.18 Lite mode (on by default on phones): avatars sit still and animate only after a tap, a state
// change or a pointer move near them; nothing animates offscreen or while the tab is hidden.
const LITE={on:false};function wake(b,ms){b.wakeUntil=Math.max(b.wakeUntil||0,performance.now()+(ms||2500))}
addEventListener('pointerdown',()=>BOTS.forEach(b=>wake(b,3000)),{passive:true});
let tick=0;function frame(now){if(!manual){const gap=LITE.on?50:(document.hasFocus()?33:250);if(document.hidden){lastT=null;setTimeout(()=>requestAnimationFrame(frame),500);return}if(lastT!=null&&now-lastT<gap){requestAnimationFrame(frame);return}tick++;const dt=lastT==null?0:Math.min(.25,(now-lastT)/1000);lastT=now;if(!document.hidden){for(let i=BOTS.length-1;i>=0;i--){const b=BOTS[i];if(!b.svg.isConnected){if(b.seen)BOTS.splice(i,1);continue}b.seen=true;if(b.visible&&(!LITE.on||(b.wakeUntil||0)>now||!b.drawn)&&(b.big||tick%3===0)&&b.svg.getClientRects().length){b.update(b.big?dt:dt*3);b.drawn=true}}}}requestAnimationFrame(frame)}
requestAnimationFrame(frame);
addEventListener('pointermove',e=>BOTS.forEach(b=>b.look(e.clientX,e.clientY)));
function step(sec,fps=60){manual=true;for(let i=0;i<Math.round(sec*fps);i++)BOTS.forEach(b=>b.update(1/fps))}
window.PedBot={create,step,lite:LITE,wake,SHAPES,CLIPS,STATES,bots:BOTS,REDUCED};
})();
