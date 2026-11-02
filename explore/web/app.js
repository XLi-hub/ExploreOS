"use strict";
const API="/api/v1/exploreos";
let selected=null,tab="brief",snapshot=null,refreshing=false,controlling=false,projectIndex=[],runtimeInfo=null,executionIntent=false,controlIntent=null,starterIntent=null;
const $=id=>document.getElementById(id);
const words={report:"综合报告",recorded:"已记录",stale:"过期未生效",inference:"推断",hypothesis:"假设",fact:"事实主张（待核查）",analogy:"类比",idea:"构想",retain:"保留",revise:"修订",withdraw:"撤回",uncertain:"暂不判断",incomplete_execution_case:"执行记录待核对",starting:"准备中",running:"执行中",failed:"执行失败",failed_before_dispatch:"派发前失败",invalid_output:"输出需修正",unknown:"结果待核对",received:"已收到，待核对",cancelling:"正在取消",cancelled:"已取消",timed_out:"已超时",unavailable:"来源暂不可读",changed_or_unavailable:"来源已变化或不可读",active:"可继续",paused:"已暂停",blocked:"需要核对",completed:"已完成",provisional:"暂定",contested:"有争议",superseded:"已修订",withdrawn:"已撤回",simulated:"机械演示",single:"单代理",independent:"独立多代理",collaborative:"协作多代理",multiple_perspectives:"单代理多角度",not_run:"尚未运行",mechanical_fixture:"机械演示",real_model_execution:"真实模型执行记录"};
const label=x=>words[x]||x;
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function note(text){$("message").textContent=text||""}
async function api(path,body){const key=localStorage.getItem("moltbook_api_key");const headers=key?{"Authorization":"Bearer "+key}:{};if(body!==undefined)headers["Content-Type"]="application/json";const response=await fetch(API+path.replace(/^\/api/,""),{method:body===undefined?"GET":"POST",headers,body:body===undefined?undefined:JSON.stringify(body)});const value=await response.json();if(response.ok){$("auth-hint").hidden=true;}if(response.status===401){$("auth-hint").hidden=false;throw Error("请先使用原 ClawInstitute 登录，再继续操作。")}if(!response.ok)throw Error(value.error||"请求失败");return value}
function card(title){const el=node("article",undefined,"card");if(title)el.append(node("h3",title));return el}
function details(title,value){const el=node("details");el.append(node("summary",title),node("pre",typeof value==="string"?value:JSON.stringify(value,null,2)));return el}
function tagNode(value,warning=false){return node("span",label(value),"tag"+(warning?" warning":""))}
function renderProjects(){
  const nav=$("projects");nav.replaceChildren();const query=$("project-search").value.trim().toLowerCase();
  const ordered=[...projectIndex].sort((a,b)=>Number(b.name===selected)-Number(a.name===selected));
  const matches=ordered.filter(p=>!query||(p.name+" "+p.question).toLowerCase().includes(query));
  if(!matches.length)nav.append(node("p",query?"没有匹配的问题，试试其他关键词。":"你的探索会保存在这里。","project-empty"));
  for(const p of matches){
    const b=node("button");b.append(node("div",p.question?.slice(0,46)||p.name),node("small",label(p.status)+(p.rounds!==undefined?" · "+p.rounds+" 轮记录":"")));
    b.className=p.name===selected?"selected":"";if(p.name===selected)b.setAttribute("aria-current","page");b.title=p.question||p.name;
    b.onclick=()=>{selected=p.name;location.hash=selected;load()};nav.append(b);
  }
}
async function projects(){const data=await api("/api/projects");projectIndex=data.projects;renderProjects();if(!selected&&projectIndex.length){const last=localStorage.getItem("exploreos_last_project");selected=projectIndex.some(p=>p.name===last)?last:projectIndex[0].name;location.hash=selected;await load()}}
async function load(){if(!selected)return;updateControls();if(refreshing)return;refreshing=true;$("workspace").setAttribute("aria-busy","true");updateControls();const requested=selected;try{const received=await api(`/api/project/${requested}/state`);if(selected!==requested)return;snapshot=received;connectionStatus(true);$("native-discussion").href=snapshot.native_workspace_url;$("native-discussion").hidden=false;$("native-files").href=snapshot.native_files_url;$("native-files").hidden=false;$("empty").hidden=true;$("workspace").hidden=false;$("title").textContent="探索成果";localStorage.setItem("exploreos_last_project",selected);$("question").textContent=snapshot.question_revisions.at(-1).text;$("meta").textContent=`${label(snapshot.mode)} · ${label(snapshot.status)} · ${snapshot.rounds.length}/${snapshot.max_rounds} 轮 · ${snapshot.participant_count} 人 · ${label(snapshot.record_kind)} · 记录版本 ${snapshot.version}`;updateControls();if(snapshot.observation)note(snapshot.observation.detail);else if(snapshot.continuation_required)note("项目索引已达到容量边界。请导出记录，再通过带条件的记忆引用建立接续课题；原始记录完整保留。");render();renderOverview();updateControls();renderProgress();const index=projectIndex.findIndex(p=>p.name===snapshot.name),entry={name:snapshot.name,question:snapshot.question_revisions.at(-1).text,status:snapshot.status,mode:snapshot.mode,rounds:snapshot.rounds.length};if(index<0)projectIndex.unshift(entry);else projectIndex[index]={...projectIndex[index],...entry};renderProjects()}catch(error){connectionStatus(false);note(error.message)}finally{refreshing=false;$("workspace").setAttribute("aria-busy","false");updateControls();if(selected!==requested)load()}}
function render(){const out=$("content");out.replaceChildren();if(!snapshot)return;
if(tab==="brief"){renderStageReport(out);renderBrief(out);}
if(tab==="findings"){const findings=snapshot.posts.filter(p=>p.phase==="reflect");if(!findings.length)out.append(node("p","尚无发现。推进一轮后，这里会保留发现、来源和未决问题。","subtle"));for(const p of findings){const k=(snapshot.knowledge||{})[p.id]||{},c=p.content,a=card();a.id="finding-"+p.id;a.append(tagNode(k.status||"provisional",k.status==="contested"),tagNode(`第 ${p.round} 轮 · 问题 v${p.question_revision}`),node("h3",c.finding));if(c.evidence)a.append(node("p",`${c.evidence.source_id} · 原文第 ${c.evidence.original_line||c.evidence.line} 行：${c.evidence.quote}`,"citation"));else a.append(node("p","此步只做推理，没有外部材料支持。","citation"));a.append(node("p","未决："+c.unresolved));for(const ch of k.challenges||[])a.append(node("p","质疑："+ch.reason+(ch.author_responses?.length?"（已有署名回应，异议仍保留）":"（尚无作者回应）")));for(const r of Object.values(snapshot.source_assessments||{}).filter(r=>r.target_post===p.id))a.append(node("p",`${r.reviewer} · ${r.verdict}：${r.reason}；范围：${r.scope}`,"small"));a.append(details("贡献与复查记录",{post_id:p.id,influenced_by:c.influenced_by,review:c.review,revisit_when:c.revisit_when}));const buttons=node("div",undefined,"actions"),audit=node("button","查看原文并核查"),challenge=node("button","提出质疑");audit.onclick=()=>auditFinding(p.id,a);challenge.onclick=async()=>{const reason=prompt("指出这条主张的具体问题");if(reason)await control("challenge",{post_id:p.id,reason})};buttons.append(audit,challenge);a.append(buttons);out.append(a)}}
if(tab==="directions"){for(const d of Object.values(snapshot.directions||{})){const a=card(d.title);a.append(tagNode(d.status),node("p","当前成员："+(d.members.join("、")||"暂时没有成员")),node("p","版本 "+d.version,"small"));a.append(details("形成依据",{proposal_post:d.proposal_post,id:d.id}));out.append(a)}out.append(details("方向变化前后与确认记录",{history:snapshot.direction_history,pending:snapshot.changes}))}
if(tab==="history"){const q=card("问题如何变化");for(const v of snapshot.question_revisions)q.append(node("p",`v${v.number} · ${v.author}：${v.text}`));out.append(q);for(const r of snapshot.reviews||[]){const a=card(label(r.decision)+" · "+label(r.status));a.append(node("p",r.reason),node("p",`原发现 ${r.target_post} → 回应 ${r.response_post}`,"small"),details("实际取回与回应依据",r));out.append(a)}out.append(details("事件时间线",snapshot.events))}
if(tab==="sources"){if(!snapshot.sources.length)out.append(node("p","还没有来源材料。添加原文后，参与者才能检查材料；没有材料时只做推理。","empty-state"));for(const s of snapshot.sources){const a=card(s.title);a.append(node("p",s.id+" · "+s.sha256,"small"));a.append(node("pre",s.lines.map((line,i)=>`${s.start_line+i}: ${line}`).join("\n")));out.append(a)}}
if(tab==="memory"){const top=node("div",undefined,"inline-controls"),add=node("button","引用其他课题发现");add.dataset.mutable="true";add.disabled=Boolean(snapshot.evaluation_binding);add.onclick=openMemory;top.append(add,node("p","每次取用会重新检查来源是否有争议、已修订或撤回；引用不是通用事实。","small"));out.append(top);const observations=new Map((snapshot.linked_memory_observations||[]).map(x=>[x.id,x]));for(const entry of Object.values(snapshot.cross_project_memory||{})){const observed=observations.get(entry.id),a=card(entry.preview);a.append(node("p","适用条件："+entry.conditions),node("p","参考理由："+entry.transfer_reason),node("p",observed?"来源当前状态："+label(observed.origin_status)+(observed.historical_basis_changed?"；来源已有变化，需要重新判断适用性。":"；仍需检查适用性。"):"历史引用；本次仅复查最近三条，请回到来源核对。","small"));const origin=node("a","打开来源课题");origin.href="/api/v1/exploreos/ui#"+encodeURIComponent(entry.origin_project);origin.target="_blank";origin.rel="noopener";a.append(origin,details("出处与历史指纹",entry));out.append(a)}if(!Object.keys(snapshot.cross_project_memory||{}).length)out.append(node("p","尚未关联其他课题的发现。","empty-state"))}
if(tab==="execution"){const a=card("调用与执行状态"),reconcile=node("button","核对中断执行");reconcile.onclick=()=>control("reconcile");a.append(node("p","调用完成、同伴赞同和引文匹配都不等于主张已经成立。","subtle"),node("p",`已使用 ${snapshot.rounds.length} / ${snapshot.max_rounds} 轮；追加轮次不会增加模型总预算。`,"small"),reconcile);for(const call of snapshot.calls){const row=node("div");row.append(node("p",`${call.actor} · ${call.phase} · ${label(call.status)} · 第 ${call.round} 轮`));if(["failed","failed_before_dispatch","invalid_output"].includes(call.status)){const retry=node("button","授权修正后重试");retry.onclick=async()=>{const reason=prompt("说明已做的修正或这次重试的理由。授权后不会立刻调用模型，请核对状态再推进。");if(reason)await control("retry",{slot:call.slot,call_id:call.id,reason})};row.append(retry)}if(call.status==="unknown")row.append(node("p","结果未知：先核对原请求，额度保留，不自动重发。","small"));a.append(row)}if(snapshot.retired_calls?.length)a.append(details("历史失败尝试（已保留）",snapshot.retired_calls));a.append(details("执行观察",snapshot.observation||{}));out.append(a)}
}
async function auditFinding(id,container){try{const audit=await api(`/api/project/${selected}/audit/${id}`);const el=details("核查原始依据",audit.basis);el.open=true;container.append(el);const save=node("button","保存这次来源核查");container.append(save);save.onclick=async()=>{try{const verdict=prompt("来源支持判断：supports / partial / unsupported / uncertain","uncertain");if(!verdict)return;const scope=prompt("原文支持到哪里，尚不支持什么？");if(!scope)return;const reason=prompt("核查理由");if(!reason)return;await control("assess",{post_id:id,basis_sha256:audit.basis_sha256,verdict,scope,reason,reviewer:"user",assessment_id:crypto.randomUUID()})}catch(error){note(error.message)}}}catch(error){note(error.message)}}
async function control(action,data={}){if(controlling||!snapshot||snapshot.name!==selected)return false;if(["advance","report"].includes(action)&&providerUnavailable()){renderProviderStatus();note("请先完成真实模型配置，再开始执行。");return false}const target=selected;controlling=true;updateControls();note("正在保存…");try{await api(`/api/project/${target}/${action}`,data);await load();if(selected!==target)return true;note(action==="advance"?"已提交推进请求；实际进度以项目状态为准。":action==="report"?"已提交综合报告请求；报告使用已保存发现，实际进度以项目状态为准。":"已保存");return true}catch(error){note(error.message);return false}finally{controlling=false;updateControls()}}
for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{tab=b.dataset.tab;selectTab();render()};
for(const b of document.querySelectorAll("[data-action]"))b.onclick=async()=>{
  const action=b.dataset.action;
  if(action==="report"){
    tab="brief";selectTab();
    if(snapshot.brief?.reports?.some(item=>item.current)){render();return;}
    if(!snapshot.native_execution){note("请先在探索设置中保存与本课题一致的执行方式。");return;}
    await control("report");
  }else if(action==="steer"||action==="extend")openControl(action);
  else if(action==="advance"){
    if(!snapshot.native_execution)await openExecution(true);
    else await control(action);
  }else await control(action);
};
async function openCreate(starter=null){
  starterIntent=typeof starter==="string"?starter:null;
  const form=$("create-form");form.reset();$("create-error").textContent="";
  $("starter-note").hidden=!starterIntent;
  const prompts={product:"怎样判断一个 AI 产品需求，值得长期投入？",knowledge:"知识库为什么越积越多，却越来越难复用？",research:"自主代理的演示，为什么与长期使用有差距？",demo:"怎样在改变问题后继续保留有用的分歧？"};
  if(starterIntent)form.elements.question.value=prompts[starterIntent]||"";
  $("starter-note").textContent=starterIntent==="demo"?"这个示例会附上一份访谈片段。创建后点击「推进一轮」，体验预设情景、来源追溯和改向；不会调用模型。":"这是一个起点，你可以改成自己的问题。";
  if(starterIntent==="demo")form.elements.backend.value="simulated";
  $("create-dialog").showModal();form.elements.question.focus();
  await readRuntime();
  showRuntime(form);
}
$("new-project").onclick=openCreate;$("empty-create").onclick=openCreate;
$("close-dialog").onclick=()=>$("create-dialog").close();
$("create-form").onsubmit=async e=>{
  e.preventDefault();const submit=e.target.querySelector('[type="submit"]');submit.disabled=true;
  try{
    const data=Object.fromEntries(new FormData(e.target));data.participants=Number(data.participants);data.concurrency=Number(data.concurrency);data.execution=executionInput(e.target);delete data.backend;delete data.budget_cny;
    const result=await api("/api/projects",data);selected=result.name;location.hash=selected;
    $("create-dialog").close();e.target.reset();tab="brief";selectTab();await load();
    if(starterIntent==="demo"&&data.execution.backend==="simulated"){
      try{await api(`/api/project/${result.name}/add-source`,{title:"示例材料 · 访谈片段",text:"初次访谈只覆盖三位老成员，不能代表所有使用者。\n成员认为保留反对意见比立即获得一致结论更有帮助。\n新成员加入后，需要重新检查旧发现的适用范围。\n"});await load();note("零付费示例已准备好。点击「推进一轮」，再查看发现、来源和分歧。");}
      catch(error){note("问题已保存，但示例材料未添加："+error.message+"。可手动添加材料。");}
    }else note("问题已保存。可添加材料，再开始第一轮。");
    starterIntent=null;
  }catch(error){$("create-error").textContent=error.message}finally{submit.disabled=false}
};
$("refresh").onclick=async()=>{await readRuntime();await load();await projects()};$("download").onclick=async()=>{try{const data=await api(`/api/project/${selected}/export`);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=selected+"-export.json";a.click();URL.revokeObjectURL(url)}catch(error){note(error.message)}};
selected=/^[a-z0-9_]{1,24}$/.test(location.hash.slice(1))?location.hash.slice(1):null;projects().then(()=>selected&&load()).catch(e=>note(e.message));setInterval(()=>selected&&!document.hidden&&!document.querySelector("#content details[open],dialog[open]")&&load(),6000);

$("project-search").oninput=renderProjects;
setInterval(()=>!document.hidden&&!document.querySelector("dialog[open]")&&projects().catch(e=>note(e.message)),60000);

function sourceInput(form){const data=Object.fromEntries(new FormData(form));if(!data.title.trim()||!data.text.trim()||new TextEncoder().encode(data.text).length>12000||data.text.split(/\r\n|\r|\n/).length-(data.text.endsWith("\n")?1:0)>80)throw Error("请填写标题与原文，每份材料最多 80 行、12 KB。");return{title:data.title,text:data.text}}
$("add-source").onclick=()=>{$("source-error").textContent="";$("source-dialog").showModal()};
$("close-source").onclick=()=>$("source-dialog").close();
$("source-file").onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>12000)throw Error("文件超过 12 KB，请选取相关片段后添加。");const form=$("source-form");form.elements.text.value=new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());if(!form.elements.title.value)form.elements.title.value=file.name;sourceInput(form);sourceCount();$("source-error").textContent=""}catch(error){$("source-error").textContent=error.message}};
$("source-form").onsubmit=async event=>{event.preventDefault();const submit=event.target.querySelector('[type="submit"]');submit.disabled=true;try{const data=sourceInput(event.target);await api(`/api/project/${selected}/add-source`,data);$("source-dialog").close();event.target.reset();document.querySelector('[data-tab="sources"]').click();await load();note("材料已保存；之后的检查会保留原文版本与行号。")}catch(error){$("source-error").textContent=error.message}finally{submit.disabled=false}};
let memoryFindings=[];
async function memoryOrigin(){const form=$("memory-form"),name=form.elements.origin_name.value;form.elements.post_id.replaceChildren(new Option("正在读取发现…",""));form.elements.post_id.disabled=true;$("memory-preview").textContent="";if(!name)return;try{const origin=await api(`/api/project/${name}/state`);if(form.elements.origin_name.value!==name)return;memoryFindings=origin.posts.filter(post=>post.phase==="reflect").map(post=>({...post,status:origin.knowledge?.[post.id]?.status||"provisional"}));form.elements.post_id.replaceChildren(...memoryFindings.map(post=>new Option(label(post.status)+" · "+post.content.finding.slice(0,160),post.id)));if(!memoryFindings.length)form.elements.post_id.append(new Option("来源课题还没有发现",""));form.elements.post_id.disabled=!memoryFindings.length;memoryPreview()}catch(error){$("memory-error").textContent=error.message}}
function memoryPreview(){const post=memoryFindings.find(p=>p.id===$("memory-form").elements.post_id.value);$("memory-preview").textContent=post?post.content.finding+"\n未决："+post.content.unresolved:""}
async function openMemory(){const form=$("memory-form");form.reset();$("memory-error").textContent="";const origins=projectIndex.filter(p=>p.name!==selected&&p.status!=="unavailable");form.elements.origin_name.replaceChildren(...origins.map(p=>new Option(p.name+" · "+p.question.slice(0,70),p.name)));if(!origins.length)form.elements.origin_name.append(new Option("还没有其他可参考的课题",""));$("memory-dialog").showModal();await memoryOrigin()}
$("memory-form").elements.origin_name.onchange=memoryOrigin;$("memory-form").elements.post_id.onchange=memoryPreview;$("close-memory").onclick=()=>$("memory-dialog").close();
$("memory-form").onsubmit=async event=>{event.preventDefault();const submit=event.target.querySelector('[type="submit"]');submit.disabled=true;try{const data=Object.fromEntries(new FormData(event.target));if(!data.origin_name||!data.post_id)throw Error("请选择已有发现的来源课题。");await api(`/api/project/${selected}/link-memory`,data);$("memory-dialog").close();await load();note("已保存带出处与适用条件的引用。")}catch(error){$("memory-error").textContent=error.message}finally{submit.disabled=false}};

function updateControls(){if(!snapshot)return;renderProviderStatus();const providerBlocked=providerUnavailable();const switching=snapshot.name!==selected;const exhausted=snapshot.rounds.length>=snapshot.max_rounds&&["completed","cancelled"].includes(snapshot.rounds.at(-1)?.status);$("round-limit").hidden=!exhausted||Boolean(snapshot.evaluation_binding);$("add-source").disabled=controlling||switching||Boolean(snapshot.evaluation_binding);for(const button of document.querySelectorAll("[data-action]"))button.disabled=controlling||switching||(button.dataset.action==="report"&&(providerBlocked||!snapshot.rounds.length||snapshot.rounds.at(-1).status!=="completed"||snapshot.rounds.at(-1).question_revision!==snapshot.question_revisions.at(-1).number||snapshot.status!=="active"||Boolean(snapshot.evaluation_binding)))||(button.dataset.action==="extend"&&Boolean(snapshot.evaluation_binding))||(button.dataset.action==="advance"&&(providerBlocked||Boolean(snapshot.evaluation_binding)||exhausted||snapshot.status!=="active"));$("execution-settings").disabled=controlling||switching||Boolean(snapshot.evaluation_binding);for(const button of document.querySelectorAll("#content button"))button.disabled=controlling||switching||(button.dataset.mutable==="true"&&Boolean(snapshot.evaluation_binding))}
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1)||projectIndex[0]?.name;if(next&&next!==selected){if(!/^[a-z0-9_]{1,24}$/.test(next)){note('项目名称格式不正确。');return}selected=next;load()}});

function selectTab(){for(const x of document.querySelectorAll("[data-tab]")){
  const active=x.dataset.tab===tab;x.setAttribute("aria-selected",String(active));x.tabIndex=active?0:-1;
  x.id="tab-"+x.dataset.tab;x.setAttribute("aria-controls","content");
  if(active){$("content").setAttribute("aria-labelledby",x.id);$("content").removeAttribute("aria-label");}
}}
function findingLink(postId,text="查看发现与原始依据"){
  const button=node("button",text);button.onclick=()=>{tab="findings";selectTab();render();document.getElementById("finding-"+postId)?.scrollIntoView({block:"center",behavior:"smooth"})};return button;
}
function renderBrief(out){
  const brief=snapshot.brief;if(!brief)return;
  const intro=card(snapshot.record_kind==="mechanical_fixture"?"机械演示成果 · 用于体验流程":"本阶段的认识");
  intro.append(node("p",snapshot.record_kind==="mechanical_fixture"?"以下内容来自预设演示情景，帮助了解操作与记录方式，不代表模型完成了真实研究。":"以下是参与者已发布的发现与回应。每条保留署名和适用范围，尚需结合材料判断。","small"));
  intro.append(node("p",`已完成 ${brief.completed_rounds} 轮 · 当前关注点下 ${brief.findings.length} 条发现 · 保留 ${brief.questions.length} 项未决问题或质疑`));out.append(intro);
  const current=card("当前发现");
  if(!brief.findings.length)current.append(node("p",brief.historical.length?"关注点已经改变。旧发现保留在历史中，等待检查适用性；当前尚无新发现。":"开始探索后，这里会留下对问题的新认识。可先添加材料，也可以从明确标记的推理开始。","empty-state"));
  for(const item of brief.findings.slice(-6).reverse()){
    const el=node("section",undefined,"brief-item");el.append(tagNode(item.status,item.status==="contested"),tagNode(item.claim_kind),node("h3",item.text));
    el.append(node("p",`${item.actor} · 第 ${item.round} 轮 · 问题 v${item.question_revision}`,"small"));
    if(item.evidence){const source=snapshot.sources.find(s=>s.id===item.evidence.source_id);el.append(node("p",`${source?.title||item.evidence.source_id} · 第 ${item.evidence.original_line||item.evidence.line} 行：${item.evidence.quote}`,"citation"))}
    else el.append(node("p","本项只有推理，尚无外部材料支持。","citation"));
    el.append(findingLink(item.post_id));current.append(el);
  }
  if(brief.findings.length>6){const all=node("button",`查看全部 ${brief.findings.length} 条发现`);all.onclick=()=>{tab="findings";selectTab();render()};current.append(all)}out.append(current);
  const changes=card("哪些认识发生了变化");
  if(!brief.changes.length)changes.append(node("p","尚无已记录的旧认识复查回应。","small"));
  for(const item of brief.changes.slice(-6).reverse())changes.append(node("p",`${label(item.decision)}：${item.reason}`),node("p",`${item.actor} · ${label(item.status)}；回应保留，原异议仍可检查。`,"small"),findingLink(item.response_post,"查看回应及其依据"));
  if(brief.stale_reviews.length)changes.append(node("p",`另保留 ${brief.stale_reviews.length} 条过期未生效的复查回应，可在认识变化中查看。`,"small"));
  const directionCount=snapshot.direction_history?.length||0;
  if(directionCount){const button=node("button",`查看 ${directionCount} 次方向或分工变化`);button.onclick=()=>{tab="directions";selectTab();render()};changes.append(button)}out.append(changes);
  const questions=card("仍有哪些分歧与未知");
  if(!brief.questions.length)questions.append(node("p","尚无已发布的未决记录；这不代表问题已解决。","small"));
  for(const item of brief.questions.slice(-6).reverse())questions.append(node("p",(item.kind==="challenge"?"质疑：":"待检查：")+item.text),item.responded?node("p","已有署名回应，异议仍保留。","small"):node("span"),findingLink(item.post_id));
  if(brief.questions.length>6)questions.append(details(`全部 ${brief.questions.length} 项未决记录`,brief.questions));out.append(questions);
  const next=card("下一步值得做什么");next.append(node("p",brief.next_step),node("p","具体研究路线由参与者结合问题与材料提出；这里提示当前可进行的操作。","small"));out.append(next);
  if(brief.historical.length){const history=card(`历史发现 · ${brief.historical.length} 条`);history.append(node("p","旧关注点下的发现、已修订及撤回记录保留；再次沿用前应检查适用性。","small"));for(const item of brief.historical.slice(-3).reverse())history.append(node("p",item.text),node("p",`问题 v${item.question_revision} · ${label(item.status)}`,"small"),findingLink(item.post_id));out.append(history)}
}
function renderProgress(){
  const brief=snapshot.brief,backend=snapshot.native_execution?.backend;
  $("progress").textContent=snapshot.calls.some(c=>["unknown","received"].includes(c.status))?"本轮有调用结果需要核对，请打开运行状态查看；未知额度继续保留。":brief?.outstanding_calls?`正在推进：${brief.completed_calls} 次调用已完成，${brief.outstanding_calls} 次待完成或核对。可以离开页面，回来后查看实际记录。`:brief?.failed_calls?"本轮有执行需要处理，请在运行状态中检查。":snapshot.calls.length?`已保存 ${brief?.completed_rounds||0} 轮完整记录。${backend==="simulated"?"当前为零付费机械演示。":""}`:"尚未调用模型。可先添加材料，再开始探索。";
}
async function readRuntime(){try{runtimeInfo=await api("/api/runtime")}catch(error){runtimeInfo=null;note(error.message)}updateControls()}
function showRuntime(form){
  const real=form.elements.backend.value!=="simulated",budget=runtimeInfo?.budget;
  form.querySelector(".budget-field").hidden=!real||Boolean(budget);
  form.elements.budget_cny.required=real&&!budget;
  const messages=[];
  if(!real)messages.push("预设情景演示，零模型调用。演示和真实探索分别保存。");
  else if(!runtimeInfo)messages.push("暂时无法读取运行配置，开始前请刷新并核对。");
  else{
    messages.push(runtimeInfo.credential==="configured"?"模型凭据已配置。":"模型凭据尚未就绪，真实运行前需在服务端配置。");
    if(!runtimeInfo.pi_ready)messages.push("真实执行依赖尚未安装。");
    if(runtimeInfo.network==="not_allowed_at_startup")messages.push("本环境启动策略尚未放行模型服务，需在云环境网络设置中允许 api.deepseek.com。此处未发起连接或模型调用。");
    else messages.push("此处仅检查本机配置，供应商连接与权限会在实际运行时检查。");
    if(budget)messages.push(`共享预算上限 ¥${budget.limit_cny}，已结算及保留额度 ¥${budget.exposure_cny.toFixed(4)}，请求 ${budget.requests}/${budget.max_calls}。${budget.unknown_requests?`${budget.unknown_requests} 项结果未知，额度继续保留。`:""}`);
  }
  form.querySelector(".runtime-hint").textContent=messages.join("\n");
}
function executionInput(form){
  const backend=form.elements.backend.value;if(backend==="simulated")return{backend};
  const budget_cny=runtimeInfo?.budget?.limit_cny??Number(form.elements.budget_cny.value);
  if(!Number.isFinite(budget_cny)||budget_cny<=0)throw Error("请填写大于零的共享预算上限。");
  return{backend,budget_cny};
}
async function openExecution(start=false){
  executionIntent=start;const form=$("execution-form");form.reset();$("execution-error").textContent="";
  const previous=snapshot.native_execution?.backend||snapshot.calls[0]?.backend||snapshot.retired_calls?.[0]?.backend||"pi";
  form.elements.backend.value=previous;form.elements.backend.disabled=Boolean(snapshot.calls.length||snapshot.retired_calls?.length);
  form.querySelector('[type="submit"]').textContent=start?"保存并开始本轮":"保存设置";
  $("execution-dialog").showModal();await readRuntime();showRuntime(form);
}
$("execution-settings").onclick=()=>openExecution(false);$("close-execution").onclick=()=>$("execution-dialog").close();
for(const id of ["create-form","execution-form"])$(id).elements.backend.onchange=()=>showRuntime($(id));
$("execution-form").onsubmit=async event=>{
  event.preventDefault();const submit=event.target.querySelector('[type="submit"]');submit.disabled=true;
  try{const profile=executionInput(event.target);const saved=await control("configure-execution",profile);if(!saved)return;$("execution-dialog").close();if(executionIntent)await control("advance")}catch(error){$("execution-error").textContent=error.message}finally{submit.disabled=false}
};
function openControl(action){
  controlIntent=action;const steer=action==="steer";$("control-title").textContent=steer?"修改关注点":"追加探索轮次";
  const input=node(steer?"textarea":"input");input.name="value";input.required=true;
  if(steer){input.rows=4;input.maxLength=3000;input.value=snapshot.question_revisions.at(-1).text}
  else{input.type="number";input.min="1";input.max="20";input.step="1";input.value="1"}
  $("control-label").replaceChildren(node("span",steer?"接下来想重点弄清楚什么？":"追加多少轮？"),input);
  $("control-explanation").textContent=steer?"原始问题与历史发现保留。旧结论沿用前需要重新检查适用范围。":"每次追加 1–20 轮，原共享模型预算保持不变。保存后再手动推进。";
  $("control-error").textContent="";$("control-dialog").showModal();
}
$("close-control").onclick=()=>$("control-dialog").close();
$("control-form").onsubmit=async event=>{event.preventDefault();const value=event.target.elements.value.value;const saved=await control(controlIntent,controlIntent==="steer"?{question:value}:{rounds:Number(value)});if(saved)$("control-dialog").close();else $("control-error").textContent=$("message").textContent};
$("download-brief").onclick=()=>{if(!snapshot?.brief)return;const url=URL.createObjectURL(new Blob([snapshot.brief.markdown],{type:"text/markdown;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download=snapshot.name+"-brief.md";a.click();URL.revokeObjectURL(url)};

function connectionStatus(ok){
  const el=$("connection-status");el.hidden=ok;
  el.textContent=ok?"":"连接暂时中断，正在尝试重新读取。未确认的操作请先检查项目状态，再决定是否重试。";
}
function renderOverview(){
  const out=$("project-overview"),brief=snapshot.brief;out.replaceChildren();
  for(const [value,title] of [[brief?.findings.length||0,"当前发现"],[brief?.questions.length||0,"分歧与未知"],[snapshot.sources.length,"来源材料"],[brief?.completed_rounds||0,"完成轮次"]]){
    const item=node("div",undefined,"overview-item");item.append(node("strong",String(value)),node("span",title));out.append(item);
  }
}
for(const button of document.querySelectorAll("[data-starter]"))button.onclick=()=>openCreate(button.dataset.starter);
$("start-demo").onclick=()=>openCreate("demo");
$("open-guide").onclick=()=>$("guide-dialog").showModal();
$("close-guide").onclick=()=>$("guide-dialog").close();
function applyTheme(theme){
  document.documentElement.dataset.theme=theme;
  const dark=theme==="dark";$("theme-toggle").textContent=dark?"浅色外观":"深色外观";
  $("theme-toggle").setAttribute("aria-label",dark?"切换浅色外观":"切换深色外观");
}
applyTheme(localStorage.getItem("exploreos_theme")==="dark"?"dark":"light");
$("theme-toggle").onclick=()=>{const theme=document.documentElement.dataset.theme==="dark"?"light":"dark";localStorage.setItem("exploreos_theme",theme);applyTheme(theme)};
document.addEventListener("keydown",event=>{
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){event.preventDefault();$("project-search").focus();$("project-search").select();}
});
document.querySelector(".tabs").addEventListener("keydown",event=>{
  const tabs=[...document.querySelectorAll("[data-tab]")],index=tabs.indexOf(document.activeElement);
  if(index<0||!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
  event.preventDefault();const next=event.key==="Home"?0:event.key==="End"?tabs.length-1:(index+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;
  tabs[next].click();tabs[next].focus();
});
function sourceCount(){
  const value=$("source-form").elements.text.value,bytes=new TextEncoder().encode(value).length;
  const lines=value?value.split(/\r\n|\r|\n/).length-(value.endsWith("\n")?1:0):0;
  $("source-count").textContent=lines+" / 80 行 · "+bytes.toLocaleString()+" / 12,000 字节";
  $("source-count").classList.toggle("over-limit",lines>80||bytes>12000);
}
$("source-form").elements.text.addEventListener("input",sourceCount);
$("source-dialog").addEventListener("close",sourceCount);
selectTab();

$("guide-demo").onclick=()=>{$("guide-dialog").close();openCreate("demo")};

function renderStageReport(out){
  const entries=snapshot.brief?.reports||[],latest=[...entries].reverse().find(item=>item.current);
  const button=document.querySelector('[data-action="report"]');
  if(button)button.textContent=latest?"查看综合报告":"生成综合报告";
  if(latest){
    const report=latest.content,a=card(report.title);a.classList.add("stage-report");
    a.append(tagNode(snapshot.record_kind==="mechanical_fixture"?"机械演示":"综合判断 · 保留限制"),node("p",report.overview));
    for(const [field,title,textKey,detailKey] of [["conclusions","阶段判断","claim","caveat"],["disagreements","竞争解释与分歧","issue","implication"],["next_steps","建议的下一步","action","reason"]]){
      if(!report[field].length)continue;
      a.append(node("h3",title));
      for(const item of report[field]){
        const part=node("section",undefined,"brief-item");part.append(node("p",item[textKey]),node("p",(field==="conclusions"?"适用限制：":"")+item[detailKey],"small"));
        for(const id of item.basis)part.append(findingLink(id,"核对依据"));
        a.append(part);
      }
    }
    a.append(node("h3","仍待弄清楚"));
    for(const text of report.unknowns)a.append(node("p",text));
    a.append(node("p","这份综合判断来自已有发现。原始异议、来源核查与未决问题继续保留在下方；报告不增加外部证据。","small"));
    if(report.omitted_finding_ids?.length)a.append(node("p","另有 "+report.omitted_finding_ids.length+" 条发现未纳入本次模型上下文，可在完整记录中检查。","small"));
    out.append(a);
  }
  const historical=entries.filter(item=>!item.current);
  if(historical.length){const a=card("历史综合报告 · 沿用前复查");for(const item of historical.slice(-3)){
    const el=node("details");el.append(node("summary",item.content.title),node("p","问题、材料、方向或认识状态已有变化，这份报告不作为当前结论。","small"),node("p",item.content.overview));a.append(el);
  }out.append(a);}
}

function providerUnavailable(){
  const backend=snapshot?.native_execution?.backend;
  if(!backend||backend==="simulated")return false;
  if(!runtimeInfo)return true;
  return runtimeInfo.credential!=="configured"||(backend==="pi"&&!runtimeInfo.pi_ready)||runtimeInfo.network==="not_allowed_at_startup";
}
function renderProviderStatus(){
  const el=$("provider-status");el.hidden=!providerUnavailable();
  if(el.hidden)return;
  if(!runtimeInfo){el.textContent="暂时无法读取真实模型配置。请刷新确认；问题和材料仍可保存。";return;}
  const messages=["真实探索尚未就绪。问题和材料可以保存，执行前请完成模型配置。"];
  if(runtimeInfo.credential!=="configured")messages.push("请通过「模型设置」保存 DeepSeek API 密钥；也可由安装主机的 DEEPSEEK_API_KEY 提供。模型密钥不填入登录页。");
  if(snapshot.native_execution?.backend==="pi"&&!runtimeInfo.pi_ready)messages.push("Pi 执行依赖尚未就绪；源码安装请运行 bash scripts/cloud/setup_pi.sh。");
  if(runtimeInfo.network==="not_allowed_at_startup")messages.push("本环境的启动网络策略尚未允许模型服务，需要先恢复供应商网络访问。");
  messages.push("需要体验流程时，请在使用指南中明确打开零付费示例。");
  el.textContent=messages.join("\n");
  const setup=node("button","打开模型设置");setup.onclick=openProvider;el.append(node("br"),setup);
}
readRuntime();

let providerVersion=null,providerSaving=false;
function providerSummary(){
  const form=$("provider-form"),canManage=runtimeInfo?.can_manage_provider===true,editable=runtimeInfo?.credential_editable===true;
  const source=runtimeInfo?.credential_source;
  const sources={local:"本机私有配置 · 已保存",environment:"由环境变量提供 · 本页只读",legacy:"由原私有配置文件提供",missing:"尚未配置模型密钥",invalid:"私有配置文件权限或格式异常，请在安装主机修复"};
  $("provider-summary").textContent=runtimeInfo?(sources[source]||"配置状态待核对")+"\n保存状态不代表供应商网络或权限已验证。"+(!canManage?"\n需要实例登录令牌才能修改配置。":""):"无法读取模型配置，请返回后重试。";
  const budget=runtimeInfo?.budget;
  $("provider-budget").textContent=budget?"共享预算 ¥"+budget.limit_cny+"，剩余准入额度 ¥"+budget.remaining_cny.toFixed(4)+"，请求 "+budget.requests+"/"+budget.max_calls+"。更换密钥不重置预算或未知请求。":"尚未创建共享预算；在新建课题或探索设置中明确设置，开始真实执行时才创建。保存密钥不产生模型费用。";
  $("provider-fields").hidden=!canManage||!editable;
  form.elements.api_key.disabled=!canManage||!editable||providerSaving;
  $("save-provider").hidden=!canManage||!editable;
  $("save-provider").disabled=providerSaving;
  $("remove-provider").hidden=!canManage||source!=="local";
  $("remove-provider").disabled=providerSaving;
  $("close-provider").disabled=providerSaving;
}
async function openProvider(){
  $("provider-form").reset();$("provider-error").textContent="";
  $("provider-dialog").showModal();await readRuntime();
  providerVersion=runtimeInfo?.credential_version??null;providerSummary();
  if(!$("provider-fields").hidden)$("provider-form").elements.api_key.focus();
}
async function changeProvider(operation){
  if(providerSaving)return;
  const key=$("provider-form").elements.api_key.value;
  if(operation==="save"&&!key.trim()){$("provider-error").textContent="请输入要保存的 DeepSeek API 密钥。";return;}
  providerSaving=true;providerSummary();$("provider-error").textContent="";
  try{
    await api("/api/provider",{operation,expected_version:providerVersion,...(operation==="save"?{key}:{})});
    $("provider-form").reset();await readRuntime();providerVersion=runtimeInfo?.credential_version??null;
    note(operation==="save"?"模型配置已保存；尚未发起供应商请求。准备好问题和预算后，再开始真实探索。":"本页保存的密钥已移除。环境变量或原私有配置如仍存在，会继续提供模型凭据。");
  }catch(error){
    $("provider-error").textContent=error.message+"。请核对配置状态后再操作。";
    await readRuntime();providerVersion=runtimeInfo?.credential_version??null;
  }finally{providerSaving=false;providerSummary();}
}
$("open-provider").onclick=openProvider;
$("close-provider").onclick=()=>$("provider-dialog").close();
$("provider-dialog").addEventListener("close",()=>{$("provider-form").reset();$("provider-error").textContent="";});
$("provider-dialog").addEventListener("cancel",event=>{if(providerSaving)event.preventDefault();});
$("provider-form").onsubmit=event=>{event.preventDefault();changeProvider("save");};
$("remove-provider").onclick=()=>changeProvider("remove");
