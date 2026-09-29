/* =========================================================================
   WADIPASS common.js v12
   - 포맷터 / 차트 라이브러리(SVG·HTML) / 동기화 유틸
   - 모든 차트는 값 라벨 + 표 보기(details)를 함께 제공합니다.
     (색만으로 정보를 전달하지 않기 위한 원칙)
   ========================================================================= */

/* ------------------------------- 포맷터 -------------------------------- */
const fmt = v => (v === null || v === undefined || Number.isNaN(v)) ? '-' : (typeof v === 'number' ? v.toLocaleString('ko-KR') : v);
const pct = v => (v === null || v === undefined) ? '-' : `${Number(v).toFixed(1)}%`;
const pct0 = v => (v === null || v === undefined) ? '-' : `${Math.round(Number(v))}%`;
const money = v => (v === null || v === undefined) ? '-' : `${Math.round(v).toLocaleString('ko-KR')}원`;
const nz = v => (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) ? null : Number(v);
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function q(id){return document.getElementById(id)}
function clamp(v,a=0,b=100){return Math.max(a,Math.min(b,Number(v)||0))}

/* 시리즈 컬러: 고정 순서로만 배정합니다(순위에 따라 재배정하지 않음). */
const SERIES = ['#4672F9','#0E9497','#EB6834'];
const SCALE5 = ['#1B3A9E','#2B52C8','#4672F9','#7593F7','#9AAFF5']; // 5점 → 1점
const TRACK = '#EDF0F4';

/* ------------------------- 공통 UI 조각 -------------------------------- */
function emptyBox(msg){return `<div class="empty">${esc(msg||'표시할 응답이 아직 없습니다.')}</div>`}

/** 세부 데이터 접기 블록 — 요약은 한눈에, 원자료는 전부 확인 가능하게 */
function detailsBlock(label,inner){
  return `<details class="details"><summary>${esc(label)}</summary><div class="inside">${inner}</div></details>`;
}
/** 범용 표 */
function dataTable(cols,rows){
  if(!rows||!rows.length)return emptyBox();
  return `<div class="tablewrap"><table class="table compact"><thead><tr>${
    cols.map(c=>`<th${c.n?' style="text-align:right"':''}>${esc(c.label)}</th>`).join('')
  }</tr></thead><tbody>${
    rows.map(r=>`<tr>${cols.map((c,i)=>`<td${c.n?' class="n"':''}>${r[i]??'-'}</td>`).join('')}</tr>`).join('')
  }</tbody></table></div>`;
}
/** 범례 (2개 이상 시리즈면 항상 표시) */
function legend(items){
  return `<div class="legend">${items.map(x=>`<span class="li"><i class="sw" style="background:${x.color}"></i>${esc(x.label)}</span>`).join('')}</div>`;
}

/* --------------------------- ① 가로 막대 ------------------------------ */
/**
 * bars(items, maxN, opts)
 * items: [{label, share, count}]
 * 1순위만 진한 블루, 나머지는 같은 계열 옅은 단계 → 순위가 색으로 한 번 더 읽힙니다.
 */
function bars(items,maxN=8,opts={}){
  if(!items||!items.length)return emptyBox(opts.empty);
  const list=items.slice(0,maxN);
  const rows=list.map((x,i)=>{
    const v=clamp(x.share);
    return `<div class="barrow${i===0?' top':''}">
      <div class="lb" title="${esc(x.label)}">${esc(x.label)}${x.count!==undefined?` <span class="n">${fmt(x.count)}명</span>`:''}</div>
      <div class="bar" role="img" aria-label="${esc(x.label)} ${pct(x.share)}"><i class="${i===0?'rank0':'rankN'}" style="width:${Math.max(1.5,v)}%"></i></div>
      <div class="num">${pct(x.share)}</div>
    </div>`}).join('');
  const table=dataTable(
    [{label:'항목'},{label:'응답 수',n:true},{label:'비율',n:true}],
    items.map(x=>[esc(x.label),x.count!==undefined?fmt(x.count)+'명':'-',pct(x.share)])
  );
  const more=items.length>maxN?`전체 ${items.length}개 항목 표로 보기`:'표로 보기';
  return rows+detailsBlock(more,table);
}

/* ------------------- ② 리커트 5점 100% 스택 막대 ---------------------- */
/**
 * likertStack(dist) — dist는 5점→1점 순서의 [{label,count,share}]
 * 세그먼트 사이 2px 흰 간격으로 구분(테두리를 그리지 않습니다).
 */
function likertStack(dist){
  if(!dist||!dist.length)return emptyBox('펀딩 참여의향 유효응답이 아직 없습니다.');
  if(dist.length<=2){
    return bars(dist,5)+detailsBlock('응답 표로 보기',dataTable(
      [{label:'펀딩 참여의향'},{label:'응답 수',n:true},{label:'비율',n:true}],
      dist.map(d=>[esc(d.label),fmt(d.count)+'명',pct(d.share)])));
  }
  const segs=dist.map((d,i)=>{
    const v=clamp(d.share);
    const light=i>=3;
    const show=v>=7;
    return `<div class="seg${light?' lightink':''}" style="flex:${Math.max(v,0.6)} 1 0;background:${SCALE5[i]}"
      title="${esc(d.label)} · ${fmt(d.count)}명 · ${pct(d.share)}">${show?pct0(d.share):''}</div>`;
  }).join('');
  const lg=legend(dist.map((d,i)=>({label:String(d.label).replace(/^(\d)\s*/,'$1점 '),color:SCALE5[i]})));
  const table=dataTable([{label:'구매의향'},{label:'응답 수',n:true},{label:'비율',n:true}],
    dist.map(d=>[esc(d.label),fmt(d.count)+'명',pct(d.share)]));
  return `<div class="likert" role="img" aria-label="구매의향 분포">${segs}</div>${lg}${detailsBlock('분포 표로 보기',table)}`;
}

/* --------------------------- ③ 도넛 ----------------------------------- */
/** donut(value, caption, sub, color) — 단일 비율을 하나의 숫자로 강조 */
function donut(value,caption,sub,color){
  const v=clamp(value), c=color||SERIES[0], R=54, C=2*Math.PI*R;
  const on=C*v/100;
  return `<div class="donutcard">
    <svg viewBox="0 0 140 140" class="chart" style="max-width:132px;margin:auto" role="img" aria-label="${esc(caption)} ${pct(value)}">
      <circle cx="70" cy="70" r="${R}" fill="none" stroke="${TRACK}" stroke-width="15"/>
      <circle cx="70" cy="70" r="${R}" fill="none" stroke="${c}" stroke-width="15" stroke-linecap="round"
        stroke-dasharray="${on.toFixed(1)} ${(C-on).toFixed(1)}" transform="rotate(-90 70 70)"/>
      <text x="70" y="70" text-anchor="middle" style="font-size:25px;font-weight:800;fill:var(--ink)" dy=".35em">${pct(value)}</text>
    </svg>
    <div class="cap">${esc(caption)}</div>${sub?`<div class="sub">${esc(sub)}</div>`:''}
  </div>`;
}
/* 이전 버전 호환 */
function miniDonut(value,label){return donut(value,label)}

/* ------------------ ④ 의향 → 행동 전환 퍼널 --------------------------- */
function conversionViz(high,fund,gap,meta={}){
  if(fund===null||fund===undefined)return emptyBox('모의펀딩 행동 데이터 연결을 확인 중입니다.');
  const g=nz(gap);
  const read=g===null?'':(g>=20?'Q1 응답과 집계 시트 값의 차이가 큽니다. 데이터 연결 상태를 확인하세요.'
    :g>=10?'Q1 응답과 집계 시트 값에 차이가 있습니다. 데이터 연결 상태를 확인하세요.'
    :'Q1 응답과 집계 시트 값이 유사합니다.');
  return `<div class="funnel">
    <div class="fstep"><div class="k">Q1 펀딩 참여 의향</div><div class="v">${pct(high)}</div>
      <div class="bar"><i class="series0" style="width:${clamp(high)}%"></i></div></div>
    <div class="arrow">→</div>
    <div class="fstep"><div class="k">집계 시트 참여 응답</div><div class="v">${pct(fund)}</div>
      <div class="bar"><i class="series1" style="width:${clamp(fund)}%"></i></div></div>
  </div>
  <div class="gapbox"><span class="k">참여응답 집계 차이</span><span class="v">${g===null?'-':g.toFixed(1)+'%p'}</span>
    <span class="d">${esc(read)}</span></div>
  ${detailsBlock('전환 수치 표로 보기',dataTable([{label:'구분'},{label:'값',n:true}],[
    ['Q1 펀딩 참여 의향 비율',pct(high)],
    ['집계 시트 참여 응답 비율',pct(fund)],
    ['참여응답 집계 차이',g===null?'-':g.toFixed(1)+'%p'],
    ['관심군 응답자 수',meta.high_intent_n!==undefined?fmt(meta.high_intent_n)+'명':'-'],
    ['집계 시트 미매칭',meta.high_intent_nonfunded_n!==undefined?fmt(meta.high_intent_nonfunded_n)+'명':'-'],
  ]))}`;
}

/* ------------------ ⑤ 집단 비교 막대 (연령/성별) ---------------------- */
/** reactionBars — 집단별 펀딩 참여의향률. 표본이 작은 집단은 표시로 구분합니다. */
function reactionBars(items,opts={}){
  if(!items||!items.length)return emptyBox('표시할 반응 데이터가 없습니다.');
  const min=opts.minN??10;
  const hideSmall=Boolean(opts.hideSmall);
  const source=hideSmall ? items.filter(x=>Number(x.count||0)>=min) : items;
  if(!source.length)return emptyBox(`응답자가 ${min}명 이상인 집단이 아직 없습니다.`);
  const rows=source.map(x=>{
    const v=nz(x.high_intent_rate);
    const thin=Number(x.count||0)<min;
    return `<div class="barrow">
      <div class="lb" title="${esc(x.label)}">${esc(x.label)} <span class="n">응답 ${fmt(x.count)}명${thin?' · 응답 적음':''}</span></div>
      <div class="bar" role="img" aria-label="${esc(x.label)} 펀딩 참여의향 ${pct(v)}">
        <i class="${thin?'rankN':'rank0'}" style="width:${v===null?0:Math.max(1.5,clamp(v))}%"></i></div>
      <div class="num">${v===null?'-':pct(v)}</div>
    </div>`}).join('');
  return rows+`<div class="chartnote">${hideSmall?`응답자가 ${min}명 이상인 집단만 주요 비교에 포함했습니다.`:`응답자가 ${min}명 미만인 집단은 옅게 표시했습니다. 표본이 더 쌓인 뒤 해석하세요.`}</div>`;
}
function reactionTable(items){
  if(!items||!items.length)return emptyBox('표시할 반응 데이터가 없습니다.');
  const labelOf=v=>(v&&typeof v==='object')?(v.label||'-'):(v||'-');
  return dataTable(
    [{label:'구분'},{label:'응답',n:true},{label:'참여의향률',n:true},{label:'참여의향률',n:true},{label:'1순위 구매장벽'},{label:'1순위 매력'}],
    items.map(x=>[`<b>${esc(x.label)}</b>`,fmt(x.count)+'명',x.high_intent_rate===null||x.high_intent_rate===undefined?'-':pct(x.high_intent_rate),
      x.high_intent_rate===null||x.high_intent_rate===undefined?'-':pct(x.high_intent_rate),
      esc(labelOf(x.top_barrier)),esc(labelOf(x.top_attraction))])
  );
}

/* ------------------ ⑥ 제품 비교 막대 (관리자) ------------------------- */
function compareBars(items,valueKey='value',suffix='%'){
  if(!items||!items.length)return emptyBox('표시할 데이터가 없습니다.');
  const rows=items.map((x,i)=>{
    const v=nz(x[valueKey]);
    return `<div class="barrow">
      <div class="lb">${esc(x.label)}</div>
      <div class="bar"><i class="series${i%3}" style="width:${v===null?0:Math.max(1.5,clamp(v))}%"></i></div>
      <div class="num">${v===null?'-':v.toFixed(1)+suffix}</div>
    </div>`}).join('');
  return rows+legend(items.map((x,i)=>({label:x.label,color:SERIES[i%3]})));
}

/* ------------------ ⑦ 산점도 (세그먼트 / 포트폴리오) ------------------ */
/**
 * 라벨 겹침 방지 — 점이 몰려 있어도 이름이 서로 밟지 않도록 세로로 밀어내고
 * 점과 라벨을 얇은 연결선(leader line)으로 잇습니다.
 */
function placeLabels(pts,gap=17){
  const done=[];
  pts.slice().sort((a,b)=>a.y-b.y).forEach(p=>{
    let ly=p.y;
    let guard=0;
    while(done.some(o=>Math.abs(o.ly-ly)<gap&&Math.abs(o.x-p.x)<150)&&guard++<40) ly+=gap;
    p.ly=ly; done.push(p);
  });
  return pts;
}
function leader(p,r){
  return Math.abs(p.ly-p.y)>3
    ? `<line x1="${(p.x+r+3).toFixed(1)}" y1="${p.y.toFixed(1)}" x2="${(p.x+r+9).toFixed(1)}" y2="${p.ly.toFixed(1)}" stroke="var(--line-strong)" stroke-width="1"/>`
    : '';
}

function segmentScatter(items){
  if(!items||!items.length)return emptyBox('고객 상황 데이터가 아직 없습니다.');
  const W=720,H=340,L=56,R=170,T=22,B=52;
  const xMax=Math.max(30,...items.map(x=>Number(x.share||0)))*1.12;
  const sx=x=>L+(W-L-R)*(x/xMax), sy=y=>T+(H-T-B)*(1-clamp(y)/100);
  let svg=`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="고객 상황별 비중과 펀딩 참여의향률">`;
  [0,25,50,75,100].forEach(v=>{const yy=sy(v);svg+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" class="gridline"/><text x="${L-9}" y="${yy+4}" text-anchor="end" class="axistext">${v}%</text>`});
  const step=Math.max(10,Math.ceil(xMax/4/10)*10);
  for(let x=0;x<=xMax;x+=step){const xx=sx(x);svg+=`<line x1="${xx.toFixed(1)}" y1="${T}" x2="${xx.toFixed(1)}" y2="${H-B}" class="gridline"/><text x="${xx.toFixed(1)}" y="${H-B+20}" text-anchor="middle" class="axistext">${x}%</text>`}
  svg+=`<text x="${((L+W-R)/2).toFixed(1)}" y="${H-10}" text-anchor="middle" class="axislabel">해당 고객 비중</text>
        <text x="14" y="${((T+H-B)/2).toFixed(1)}" text-anchor="middle" transform="rotate(-90 14 ${((T+H-B)/2).toFixed(1)})" class="axislabel">펀딩 참여의향률</text>`;
  const pts=placeLabels(items.map((p,i)=>({x:sx(Number(p.share||0)),y:sy(Number(p.high_intent_rate||0)),r:7+Math.min(8,Number(p.count||0)/6),i,p})));
  pts.forEach(pt=>{svg+=`<g class="hoverable"><title>${esc(pt.p.label)} · 비중 ${pct(pt.p.share)} · 참여의향 ${pct(pt.p.high_intent_rate)} · ${fmt(pt.p.count)}명</title>${leader(pt,pt.r)}<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="${pt.r.toFixed(1)}" class="dot dot0"/></g>`});
  pts.forEach(pt=>{const lab=String(pt.p.label||''), short=lab.length>14?lab.slice(0,14)+'…':lab;svg+=`<text x="${(pt.x+pt.r+11).toFixed(1)}" y="${(pt.ly+4).toFixed(1)}" class="pointlabel">${esc(short)}</text>`});
  svg+='</svg>';
  return svg+`<div class="chartnote">오른쪽일수록 해당 고객이 많고, 위쪽일수록 Q1에서 “펀딩에 참여하겠다”고 답한 비율이 높습니다.</div>`
    +detailsBlock('고객 상황 표로 보기',dataTable(
      [{label:'고객 상황(Q2)'},{label:'응답',n:true},{label:'비중',n:true},{label:'펀딩 참여의향',n:true}],
      items.map(p=>[esc(p.label),fmt(p.count)+'명',pct(p.share),pct(p.high_intent_rate)])));
}

function portfolioScatter(items){
  const good=(items||[]).filter(x=>x.high_intent_rate!==null&&x.high_intent_rate!==undefined);
  if(!good.length)return emptyBox('Q1 펀딩 참여의향 유효응답이 쌓이면 표시됩니다.');
  const W=720,H=320,L=56,R=150,T=22,B=52;
  const sx=x=>L+(W-L-R)*(clamp(x)/100), sy=y=>T+(H-T-B)*(1-y/100);
  let svg=`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="제품별 펀딩 참여의향률과 비용 저항">`;
  [0,25,50,75,100].forEach(x=>{const xx=sx(x);svg+=`<line x1="${xx}" y1="${T}" x2="${xx}" y2="${H-B}" class="gridline"/><text x="${xx}" y="${H-B+20}" text-anchor="middle" class="axistext">${x}%</text>`});
  [0,25,50,75,100].forEach(y=>{const yy=sy(y);svg+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" class="gridline"/><text x="${L-10}" y="${yy+4}" text-anchor="end" class="axistext">${y}%</text>`});
  svg+=`<text x="${(L+W-R)/2}" y="${H-10}" text-anchor="middle" class="axislabel">펀딩 참여의향률</text><text x="16" y="${(T+H-B)/2}" text-anchor="middle" transform="rotate(-90 16 ${(T+H-B)/2})" class="axislabel">가격·비용 저항률</text>`;
  const pts=placeLabels(good.map((p,i)=>({x:sx(Number(p.high_intent_rate)),y:sy(Number(p.cost_barrier_rate||0)),r:12,i,p})));
  pts.forEach(pt=>{svg+=`<g class="hoverable"><title>${esc(pt.p.label)} · 참여의향 ${pct(pt.p.high_intent_rate)} · 비용저항 ${pct(pt.p.cost_barrier_rate)} · ${fmt(pt.p.n)}명</title>${leader(pt,pt.r)}<circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="12" class="dot dot${pt.i%3}"/></g>`});
  pts.forEach(pt=>{svg+=`<text x="${(pt.x+18).toFixed(1)}" y="${(pt.ly+4).toFixed(1)}" class="pointlabel">${esc(pt.p.label)}</text>`});
  svg+='</svg>';
  return svg+`<div class="chartnote">오른쪽은 Q1 펀딩 참여의향이 높고, 위쪽은 가격·유지비 부담이 큽니다.</div>`+legend(good.map((p,i)=>({label:p.label,color:SERIES[i%3]})));
}

/* ------------------ ⑧ 자유의견 주제 ----------------------------------- */
function textTopics(tt){
  const topics=(tt&&tt.topics)||[];
  if(!topics.length)return emptyBox('자유의견이 아직 없습니다.');
  const max=Math.max(...topics.map(t=>t.count||0))||1;
  return topics.map(t=>`<div class="topicrow">
    <div class="topichead"><b>${esc(t.label)}</b><span class="badge flat">${fmt(t.count)}건</span>
      <span class="muted small">${t.share!==undefined?pct(t.share)+' 언급':''}</span></div>
    <div class="bar" style="max-width:320px"><i class="rank0" style="width:${clamp(100*(t.count||0)/max)}%"></i></div>
    ${(t.examples||[]).map(x=>`<div class="comment">“${esc(x)}”</div>`).join('')}
  </div>`).join('');
}

/* ------------------ 동기화 / 새로고침 --------------------------------- */
function setSync(status){
  const ok=!!(status&&status.ok);
  const d=q('syncDot'); if(d)d.className='statusdot '+(ok?'ok':'');
  const t=q('syncText');
  if(t)t.textContent=ok?`실시간 연결 · ${status.last_success?new Date(status.last_success).toLocaleTimeString('ko-KR'):''}`:'연결 확인 필요';
}
let countdown=10,timer=null;
function startCountdown(seconds=10,onTick){
  countdown=seconds;clearInterval(timer);
  timer=setInterval(()=>{countdown--;if(countdown<=0)countdown=seconds;if(onTick)onTick(countdown)},1000);
}
async function forceRefresh(after){
  const b=q('refreshBtn');
  if(b){b.disabled=true;b.textContent='새로고침 중...'}
  try{if(after)await after();}
  catch(e){console.error(e)}
  finally{if(b){b.disabled=false;b.textContent='새로고침'}}
}
function statusClass(s){return (s==='양호'||s==='최종'||s==='높음')?'good':(s==='점검'?'bad':'warn')}
/** 신호 강도 → 배지 등급 (색 + 글자 라벨을 항상 함께) */
function signalClass(s){return s==='높음'?'bad':s==='중간'?'warn':s==='유지'?'good':'flat'}
