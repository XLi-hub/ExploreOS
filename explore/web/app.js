"use strict";
const API="/api/v1/exploreos";
let selected=null,tab="brief",snapshot=null,refreshing=false,controlling=false,projectIndex=[],runtimeInfo=null,executionIntent=false,controlIntent=null;
const $=id=>document.getElementById(id);
const words={recorded:"已记录",stale:"过期未生效",inference:"推断",hypothesis:"假设",fact:"事实主张（待核查）",analogy:"类比",idea:"构想",retain:"保留",revise:"修订",withdraw:"撤回",uncertain:"暂不判断",incomplete_execution_case:"执行记录待核对",starting:"准备中",running:"执行中",failed:"执行失败",failed_before_dispatch:"派发前失败",invalid_output:"输出需修正",unknown:"结果待核对",received:"已收到，待核对",cancelling:"正在取消",cancelled:"已取消",timed_out:"已超时",unavailable:"来源暂不可读",changed_or_unavailable:"来源已变化或不可读",active:"可继续",paused:"已暂停",blocked:"需要核对",completed:"已完成",provisional:"暂定",contested:"有争议",superseded:"已修订",withdrawn:"已撤回",simulated:"机械演示",single:"单代理",independent:"独立多代理",collaborative:"协作多代理",multiple_perspectives:"单代理多角度",not_run:"尚未运行",mechanical_fixture:"机械演示",real_model_execution:"真实模型执行记录"};
const label=x=>words[x]||x;
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function note(text){$("message").textContent=text||""}
async function api(path,body){const key=localStorage.getItem("moltbook_api_key");const headers=key?{"Authorization":"Bearer "+key}:{};if(body!==undefined)headers["Content-Type"]="application/json";const response=await fetch(API+path.replace(/^\/api/,""),{method:body===undefined?"GET":"POST",headers,body:body===undefined?undefined:JSON.stringify(body)});const value=await response.json();if(response.status===401){$("auth-hint").hidden=false;throw Error("请先使用原 ClawInstitute 登录，再继续操作。")}if(!response.ok)throw Error(value.error||"请求失败");return value}
function card(title){const el=node("article",undefined,"card");if(title)el.append(node("h3",title));return el}
function details(title,value){const el=node("details");el.append(node("summary",title),node("pre",typeof value==="string"?value:JSON.stringify(value,null,2)));return el}
function tagNode(value,warning=false){return node("span",label(value),"tag"+(warning?" warning":""))}
function renderProjects(){$("projects").replaceChildren();const query=$("project-search").value.toLowerCase();const ordered=[...projectIndex].sort((a,b)=>Number(b.name===selected)-Number(a.name===selected));for(const p of ordered.filter(p=>!query||(p.name+" "+p.question).toLowerCase().includes(query))){const b=node("button");b.append(node("div",p.question?.slice(0,46)||p.name),node("small",p.name+" · "+label(p.status)));b.className=p.name===selected?"selected":"";b.onclick=()=>{selected=p.name;location.hash=selected;load()};$("projects").append(b)}}
async function projects(){const data=await api("/api/projects");projectIndex=data.projects;renderProjects();if(!selected&&projectIndex.length){const last=localStorage.getItem("exploreos_last_project");selected=projectIndex.some(p=>p.name===last)?last:projectIndex[0].name;location.hash=selected;await load()}}
async function load(){if(!selected||refreshing)return;refreshing=true;const requested=selected;try{const received=await api(`/api/project/${requested}/state`);if(selected!==requested)return;snapshot=received;$("native-discussion").href=snapshot.native_workspace_url;$("native-discussion").hidden=false;$("native-files").href=snapshot.native_files_url;$("native-files").hidden=false;$("empty").hidden=true;$("workspace").hidden=false;$("title").textContent="探索成果";localStorage.setItem("exploreos_last_project",selected);$("question").textContent=snapshot.question_revisions.at(-1).text;$("meta").textContent=`${label(snapshot.mode)} · ${label(snapshot.status)} · ${snapshot.rounds.length}/${snapshot.max_rounds} 轮 · ${snapshot.participant_count} 人 · ${label(snapshot.record_kind)} · 记录版本 ${snapshot.version}`;updateControls();if(snapshot.observation)note(snapshot.observation.detail);else if(snapshot.continuation_required)note("项目索引已达到容量边界。请导出记录，再通过带条件的记忆引用建立接续课题；原始记录完整保留。");render();updateControls();renderProgress();const index=projectIndex.findIndex(p=>p.name===snapshot.name),entry={name:snapshot.name,question:snapshot.question_revisions.at(-1).text,status:snapshot.status,mode:snapshot.mode,rounds:snapshot.rounds.length};if(index<0)projectIndex.unshift(entry);else projectIndex[index]={...projectIndex[index],...entry};renderProjects()}catch(error){note(error.message)}finally{refreshing=false;if(selected!==requested)load()}}
function render(){const out=$("content");out.replaceChildren();if(!snapshot)return;
if(tab==="brief")renderBrief(out);
if(tab==="findings"){const findings=snapshot.posts.filter(p=>p.phase==="reflect");if(!findings.length)out.append(node("p","尚无发现。推进一轮后，这里会保留发现、来源和未决问题。","subtle"));for(const p of findings){const k=(snapshot.knowledge||{})[p.id]||{},c=p.content,a=card();a.id="finding-"+p.id;a.append(tagNode(k.status||"provisional",k.status==="contested"),tagNode(`第 ${p.round} 轮 · 问题 v${p.question_revision}`),node("h3",c.finding));if(c.evidence)a.append(node("p",`${c.evidence.source_id} · 原文第 ${c.evidence.original_line||c.evidence.line} 行：${c.evidence.quote}`,"citation"));else a.append(node("p","此步只做推理，没有外部材料支持。","citation"));a.append(node("p","未决："+c.unresolved));for(const ch of k.challenges||[])a.append(node("p","质疑："+ch.reason+(ch.author_responses?.length?"（已有署名回应，异议仍保留）":"（尚无作者回应）")));for(const r of Object.values(snapshot.source_assessments||{}).filter(r=>r.target_post===p.id))a.append(node("p",`${r.reviewer} · ${r.verdict}：${r.reason}；范围：${r.scope}`,"small"));a.append(details("贡献与复查记录",{post_id:p.id,influenced_by:c.influenced_by,review:c.review,revisit_when:c.revisit_when}));const buttons=node("div",undefined,"actions"),audit=node("button","查看原文并核查"),challenge=node("button","提出质疑");audit.onclick=()=>auditFinding(p.id,a);challenge.onclick=async()=>{const reason=prompt("指出这条主张的具体问题");if(reason)await control("challenge",{post_id:p.id,reason})};buttons.append(audit,challenge);a.append(buttons);out.append(a)}}
if(tab==="directions"){for(const d of Object.values(snapshot.directions||{})){const a=card(d.title);a.append(tagNode(d.status),node("p","当前成员："+(d.members.join("、")||"暂时没有成员")),node("p","版本 "+d.version,"small"));a.append(details("形成依据",{proposal_post:d.proposal_post,id:d.id}));out.append(a)}out.append(details("方向变化前后与确认记录",{history:snapshot.direction_history,pending:snapshot.changes}))}
if(tab==="history"){const q=card("问题如何变化");for(const v of snapshot.question_revisions)q.append(node("p",`v${v.number} · ${v.author}：${v.text}`));out.append(q);for(const r of snapshot.reviews||[]){const a=card(label(r.decision)+" · "+label(r.status));a.append(node("p",r.reason),node("p",`原发现 ${r.target_post} → 回应 ${r.response_post}`,"small"),details("实际取回与回应依据",r));out.append(a)}out.append(details("事件时间线",snapshot.events))}
if(tab==="sources"){if(!snapshot.sources.length)out.append(node("p","还没有来源材料。添加原文后，参与者才能检查材料；没有材料时只做推理。","empty-state"));for(const s of snapshot.sources){const a=card(s.title);a.append(node("p",s.id+" · "+s.sha256,"small"));a.append(node("pre",s.lines.map((line,i)=>`${s.start_line+i}: ${line}`).join("\n")));out.append(a)}}
if(tab==="memory"){const top=node("div",undefined,"inline-controls"),add=node("button","引用其他课题发现");add.dataset.mutable="true";add.disabled=Boolean(snapshot.evaluation_binding);add.onclick=openMemory;top.append(add,node("p","每次取用会重新检查来源是否有争议、已修订或撤回；引用不是通用事实。","small"));out.append(top);const observations=new Map((snapshot.linked_memory_observations||[]).map(x=>[x.id,x]));for(const entry of Object.values(snapshot.cross_project_memory||{})){const observed=observations.get(entry.id),a=card(entry.preview);a.append(node("p","适用条件："+entry.conditions),node("p","参考理由："+entry.transfer_reason),node("p",observed?"来源当前状态："+label(observed.origin_status)+(observed.historical_basis_changed?"；来源已有变化，需要重新判断适用性。":"；仍需检查适用性。"):"历史引用；本次仅复查最近三条，请回到来源核对。","small"));const origin=node("a","打开来源课题");origin.href="/api/v1/exploreos/ui#"+encodeURIComponent(entry.origin_project);origin.target="_blank";origin.rel="noopener";a.append(origin,details("出处与历史指纹",entry));out.append(a)}if(!Object.keys(snapshot.cross_project_memory||{}).length)out.append(node("p","尚未关联其他课题的发现。","empty-state"))}
if(tab==="execution"){const a=card("调用与执行状态"),reconcile=node("button","核对中断执行");reconcile.onclick=()=>control("reconcile");a.append(node("p","调用完成、同伴赞同和引文匹配都不等于主张已经成立。","subtle"),node("p",`已使用 ${snapshot.rounds.length} / ${snapshot.max_rounds} 轮；追加轮次不会增加模型总预算。`,"small"),reconcile);for(const call of snapshot.calls){const row=node("div");row.append(node("p",`${call.actor} · ${call.phase} · ${label(call.status)} · 第 ${call.round} 轮`));if(["failed","failed_before_dispatch","invalid_output"].includes(call.status)){const retry=node("button","授权修正后重试");retry.onclick=async()=>{const reason=prompt("说明已做的修正或这次重试的理由。授权后不会立刻调用模型，请核对状态再推进。");if(reason)await control("retry",{slot:call.slot,call_id:call.id,reason})};row.append(retry)}if(call.status==="unknown")row.append(node("p","结果未知：先核对原请求，额度保留，不自动重发。","small"));a.append(row)}if(snapshot.retired_calls?.length)a.append(details("历史失败尝试（已保留）",snapshot.retired_calls));a.append(details("执行观察",snapshot.observation||{}));out.append(a)}
}
async function auditFinding(id,container){try{const audit=await api(`/api/project/${selected}/audit/${id}`);const el=details("核查原始依据",audit.basis);el.open=true;container.append(el);const save=node("button","保存这次来源核查");container.append(save);save.onclick=async()=>{try{const verdict=prompt("来源支持判断：supports / partial / unsupported / uncertain","uncertain");if(!verdict)return;const scope=prompt("原文支持到哪里，尚不支持什么？");if(!scope)return;const reason=prompt("核查理由");if(!reason)return;await control("assess",{post_id:id,basis_sha256:audit.basis_sha256,verdict,scope,reason,reviewer:"user",assessment_id:crypto.randomUUID()})}catch(error){note(error.message)}}}catch(error){note(error.message)}}
async function control(action,data={}){if(controlling)return false;controlling=true;updateControls();note("正在保存…");try{await api(`/api/project/${selected}/${action}`,data);await load();note(action==="advance"?"已提交推进请求；实际进度以项目状态为准。":"已保存");return true}catch(error){note(error.message);return false}finally{controlling=false;updateControls()}}
for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{tab=b.dataset.tab;for(const x of document.querySelectorAll("[data-tab]"))x.setAttribute("aria-selected",String(x===b));render()};
for(const b of document.querySelectorAll("[data-action]"))b.onclick=async()=>{
  const action=b.dataset.action;
  if(action==="steer"||action==="extend")openControl(action);
  else if(action==="advance"){
    if(!snapshot.native_execution)await openExecution(true);
    else await control(action);
  }else await control(action);
};
async function openCreate(){
  $("create-form").reset();$("create-error").textContent="";$("create-dialog").showModal();
  await readRuntime();showRuntime($("create-form"));
}
$("new-project").onclick=openCreate;$("empty-create").onclick=openCreate;
$("close-dialog").onclick=()=>$("create-dialog").close();
$("create-form").onsubmit=async e=>{
  e.preventDefault();const submit=e.target.querySelector('[type="submit"]');submit.disabled=true;
  try{
    const data=Object.fromEntries(new FormData(e.target));data.participants=Number(data.participants);data.concurrency=Number(data.concurrency);data.execution=executionInput(e.target);delete data.backend;delete data.budget_cny;
    const result=await api("/api/projects",data);selected=result.name;location.hash=selected;
    $("create-dialog").close();e.target.reset();tab="brief";selectTab();await load();
    note("问题已保存。可添加材料，再开始第一轮。");
  }catch(error){$("create-error").textContent=error.message}finally{submit.disabled=false}
};
$("refresh").onclick=async()=>{await load();await projects()};$("download").onclick=async()=>{try{const data=await api(`/api/project/${selected}/export`);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=selected+"-export.json";a.click();URL.revokeObjectURL(url)}catch(error){note(error.message)}};
selected=/^[a-z0-9_]{1,24}$/.test(location.hash.slice(1))?location.hash.slice(1):null;projects().then(()=>selected&&load()).catch(e=>note(e.message));setInterval(()=>selected&&!document.querySelector("#content details[open],dialog[open]")&&load(),6000);

$("project-search").oninput=renderProjects;
setInterval(()=>!document.hidden&&!document.querySelector("dialog[open]")&&projects().catch(e=>note(e.message)),60000);

function sourceInput(form){const data=Object.fromEntries(new FormData(form));if(!data.title.trim()||!data.text.trim()||new TextEncoder().encode(data.text).length>12000||data.text.split(/\r\n|\r|\n/).length-(data.text.endsWith("\n")?1:0)>80)throw Error("请填写标题与原文，每份材料最多 80 行、12 KB。");return{title:data.title,text:data.text}}
$("add-source").onclick=()=>{$("source-error").textContent="";$("source-dialog").showModal()};
$("close-source").onclick=()=>$("source-dialog").close();
$("source-file").onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>12000)throw Error("文件超过 12 KB，请选取相关片段后添加。");const form=$("source-form");form.elements.text.value=new TextDecoder("utf-8",{fatal:true}).decode(await file.arrayBuffer());if(!form.elements.title.value)form.elements.title.value=file.name;sourceInput(form);$("source-error").textContent=""}catch(error){$("source-error").textContent=error.message}};
$("source-form").onsubmit=async event=>{event.preventDefault();const submit=event.target.querySelector('[type="submit"]');submit.disabled=true;try{const data=sourceInput(event.target);await api(`/api/project/${selected}/add-source`,data);$("source-dialog").close();event.target.reset();document.querySelector('[data-tab="sources"]').click();await load();note("材料已保存；之后的检查会保留原文版本与行号。")}catch(error){$("source-error").textContent=error.message}finally{submit.disabled=false}};
let memoryFindings=[];
async function memoryOrigin(){const form=$("memory-form"),name=form.elements.origin_name.value;form.elements.post_id.replaceChildren(new Option("正在读取发现…",""));form.elements.post_id.disabled=true;$("memory-preview").textContent="";if(!name)return;try{const origin=await api(`/api/project/${name}/state`);if(form.elements.origin_name.value!==name)return;memoryFindings=origin.posts.filter(post=>post.phase==="reflect").map(post=>({...post,status:origin.knowledge?.[post.id]?.status||"provisional"}));form.elements.post_id.replaceChildren(...memoryFindings.map(post=>new Option(label(post.status)+" · "+post.content.finding.slice(0,160),post.id)));if(!memoryFindings.length)form.elements.post_id.append(new Option("来源课题还没有发现",""));form.elements.post_id.disabled=!memoryFindings.length;memoryPreview()}catch(error){$("memory-error").textContent=error.message}}
function memoryPreview(){const post=memoryFindings.find(p=>p.id===$("memory-form").elements.post_id.value);$("memory-preview").textContent=post?post.content.finding+"\n未决："+post.content.unresolved:""}
async function openMemory(){const form=$("memory-form");form.reset();$("memory-error").textContent="";const origins=projectIndex.filter(p=>p.name!==selected&&p.status!=="unavailable");form.elements.origin_name.replaceChildren(...origins.map(p=>new Option(p.name+" · "+p.question.slice(0,70),p.name)));if(!origins.length)form.elements.origin_name.append(new Option("还没有其他可参考的课题",""));$("memory-dialog").showModal();await memoryOrigin()}
$("memory-form").elements.origin_name.onchange=memoryOrigin;$("memory-form").elements.post_id.onchange=memoryPreview;$("close-memory").onclick=()=>$("memory-dialog").close();
$("memory-form").onsubmit=async event=>{event.preventDefault();const submit=event.target.querySelector('[type="submit"]');submit.disabled=true;try{const data=Object.fromEntries(new FormData(event.target));if(!data.origin_name||!data.post_id)throw Error("请选择已有发现的来源课题。");await api(`/api/project/${selected}/link-memory`,data);$("memory-dialog").close();await load();note("已保存带出处与适用条件的引用。")}catch(error){$("memory-error").textContent=error.message}finally{submit.disabled=false}};

function updateControls(){if(!snapshot)return;const exhausted=snapshot.rounds.length>=snapshot.max_rounds&&["completed","cancelled"].includes(snapshot.rounds.at(-1)?.status);$("round-limit").hidden=!exhausted||Boolean(snapshot.evaluation_binding);$("add-source").disabled=controlling||Boolean(snapshot.evaluation_binding);for(const button of document.querySelectorAll("[data-action]"))button.disabled=controlling||(button.dataset.action==="extend"&&Boolean(snapshot.evaluation_binding))||(button.dataset.action==="advance"&&(Boolean(snapshot.evaluation_binding)||exhausted||snapshot.status!=="active"));$("execution-settings").disabled=controlling||Boolean(snapshot.evaluation_binding);for(const button of document.querySelectorAll("#content button"))button.disabled=controlling||(button.dataset.mutable==="true"&&Boolean(snapshot.evaluation_binding))}
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1)||projectIndex[0]?.name;if(next&&next!==selected){if(!/^[a-z0-9_]{1,24}$/.test(next)){note('项目名称格式不正确。');return}selected=next;load()}});

function selectTab(){for(const x of document.querySelectorAll("[data-tab]"))x.setAttribute("aria-selected",String(x.dataset.tab===tab))}
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
async function readRuntime(){try{runtimeInfo=await api("/api/runtime")}catch(error){runtimeInfo=null;note(error.message)}}
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
$("download-brief").onclick=()=>{if(!snapshot?.brief)return;const url=URL.createObjectURL(new Blob([snapshot.brief.markdown],{type:"text/markdown;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download=selected+"-brief.md";a.click();URL.revokeObjectURL(url)};
