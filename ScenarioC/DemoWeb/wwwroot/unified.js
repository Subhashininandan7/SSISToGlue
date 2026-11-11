"use strict";
/* One five-step UI for one or many SSIS packages. Backend stays package-isolated.
   Never auto-accept model diffs or infer successful SQL/SSIS parity. */
(()=>{
const $=id=>document.getElementById(id), stages=[...document.querySelectorAll('.stage')];
const titles=['Upload','Convert','Analyze & repair','Deploy','Execute & validate'];
let stage=0, portfolio=null, busy=false, proposals=new Map(), expandedPackage=null;
function show(i){stage=Math.max(0,Math.min(4,i)); stages.forEach((s,n)=>s.classList.toggle('hidden',n!==stage));
 $('progress').textContent=`Step ${stage+1} of 5`;[...$('nav').children].forEach((b,n)=>b.classList.toggle('active',n===stage));$('prev').disabled=stage===0;$('next').disabled=stage===4;
}
function report(id,v){$(id).textContent=typeof v==='string'?v:JSON.stringify(v,null,2)}
function fail(err){$('error').textContent=err.message||String(err);$('error').classList.remove('hidden')}
async function call(action,extras={}){const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Request':'1'},body:JSON.stringify({action,...extras})});
 let j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||'Request failed');return j.data;}
function base64(f){return new Promise((resolve,reject)=>{let r=new FileReader();r.onerror=()=>reject(Error('Could not read '+f.name));r.onload=()=>resolve(r.result.split(',')[1]);r.readAsDataURL(f);});}
function config(){return {profile:$('profile').value,region:$('region').value,s3Prefix:$('s3').value,glueRole:$('role').value,
 modelId:$('model').value,glueConnectionName:$('jdbc-conn').value,jdbcSecretArn:$('jdbc-secret').value,jdbcJarS3:$('jdbc-jar').value,
 approveModelCost:$('ai-cost').checked,approveCodeTransmission:$('ai-send').checked,
 approvePortfolioDeployment:$('deploy-approval').checked,approvePortfolioExecution:$('run-approval').checked,
 approveSqlServerMutations:$('approve-sql-mutations').checked};}
async function refresh(){if(!portfolio)return;portfolio=await call('bulk-status',{portfolioId:portfolio.id});render();}
function ordered(){const found=new Map(portfolio.packages.map(p=>[p.name.toLowerCase(),p]));const visiting=new Set(),done=new Set(),arr=[];
 function walk(p){let n=p.name.toLowerCase();if(done.has(n))return;if(visiting.has(n))throw Error('Cyclic SSIS package dependency: '+p.name);visiting.add(n);for(let d of p.dependencies||[]){let q=found.get(d.toLowerCase());if(q)walk(q)}visiting.delete(n);done.add(n);arr.push(p)}
 for(let p of portfolio.packages)walk(p);return arr;}
function render(){let entries=portfolio?.packages||[];$('session-label').textContent=entries.length?`${entries.length} SSIS package${entries.length===1?'':'s'} · Portfolio ${portfolio.id}`:'No packages uploaded';
 $('summary').textContent=`${entries.length} uploaded · ${entries.filter(e=>['READY_FOR_DEPLOYMENT','REPAIR_VALIDATED','AWS_VERIFIED','DEPLOYED','RUN_SUBMITTED','GLUE_SUCCEEDED','GLUE_OUTPUT_GENERATED','OUTPUTS_MATCH','PARTIAL_VALIDATION'].includes(e.state)).length} prepared · ${entries.filter(e=>e.glueStatus==='SUCCEEDED').length} Glue succeeded · ${entries.filter(e=>e.state==='OUTPUTS_MATCH').length} fully CSV validated`;
 const table=$('packages-table');table.replaceChildren();for(const p of entries){let tr=document.createElement('tr');
 for(let v of [p.name,p.state||'UPLOADED',String((p.blockers||[]).length),p.glueStatus||'—']){let td=document.createElement('td');td.textContent=v;tr.append(td)}
 let td=document.createElement('td'),btn=document.createElement('button');btn.type='button';btn.className='secondary';btn.textContent=expandedPackage===p.name?'Hide details':'Details';btn.setAttribute('aria-expanded',String(expandedPackage===p.name));btn.onclick=()=>{expandedPackage=expandedPackage===p.name?null:p.name;render();};td.append(btn);tr.append(td);table.append(tr);
 if(expandedPackage===p.name){const detailRow=document.createElement('tr');detailRow.className='package-detail-row';const cell=document.createElement('td');cell.colSpan=5;cell.append(createPackageDetails(p));detailRow.append(cell);table.append(detailRow);}
 }
}
function createPackageDetails(p){const d=document.createElement('div');d.className='package-detail';
 let t=document.createElement('p');t.textContent=`${p.name} — ${p.state||'UPLOADED'}`;d.append(t);
 let status=document.createElement('p');status.textContent=p.quickAnalysis?'Analysis already available. Re-running the bulk Analyze action may skip this package.':p.sctImported?'SCT output is available; analysis has not completed.':'No SCT-derived analysis is available yet.';d.append(status);
 if(p.lastError){let error=document.createElement('p');error.textContent='Last error: '+p.lastError;d.append(error)}
 if(p.sctWarnings?.length){let old=document.createElement('p');old.textContent='Historical SCT warnings addressed by reviewed AI: '+p.sctWarnings.join('; ');d.append(old)}
 if(p.blockers?.length){let blocked=document.createElement('p');blocked.textContent='Blockers: '+p.blockers.join('; ');d.append(blocked)}
 if(p.aiOutputS3){let cloud=document.createElement('p');cloud.textContent='AI Glue output: '+p.aiOutputS3+' · '+(p.cloudOutputValidated?'CSV files inspected':'Not verified in Glue')+' · SSIS parity: '+(p.cloudSSISParity||'NOT_PROVEN');d.append(cloud)}
 if(p.missingFolderInputs?.length){let missing=document.createElement('p');missing.textContent='Missing inputs: '+p.missingFolderInputs.join(', ');d.append(missing)}
 let links=document.createElement('div');links.className='artifact-links';let items=[];
 if(p.sctCompleted){items.push(['sct-cli-log','SCT log']);if(p.sctImported)items.push(['sct-cli-output','Original SCT output']);if(p.assessmentAvailable)items.push(['sct-assessment','SCT assessment']);}
 if(p.quickAnalysis||p.outputs?.length)items.push(['quick-scripts','Corrected scripts']);
 if(p.cloudOutputs?.length||['GLUE_FAILED','GLUE_OUTPUT_CHECK_FAILED','GLUE_OUTPUT_GENERATED'].includes(p.state))items.push(['process-ai-cloud-status','Glue output report']);
 if(p.cloudOutputArchiveAvailable)items.push(['process-ai-cloud-output','Download Glue CSV output']);
 if(p.pendingBaseHash)items.push([p.unsupportedProcessAI?'process-ai-diff':'quick-ai-diff','Bedrock diff']);
 for(let [name,label] of items){let a=document.createElement('a');a.href=`/api/artifact/${encodeURIComponent(p.sessionId)}/${name}`;a.target='_blank';a.rel='noopener';a.textContent=label;links.append(a)}
 if(!items.length){let note=document.createElement('p');note.textContent='No downloadable conversion or analysis artifacts yet.';d.append(note)}else d.append(links);
 return d;
}
async function wrapped(fn){if(busy)return;busy=true;$('error').classList.add('hidden');$('global-state').textContent='Working…';
 document.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{await fn();$('global-state').textContent='Ready'}catch(e){fail(e);$('global-state').textContent='Needs attention'}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);await refresh().catch(()=>{});show(stage);}}
async function step(p,op,extras={}){return call('bulk-step',{portfolioId:portfolio.id,packageName:p.name,operation:op,...config(),...extras});}
async function all(op,filter=()=>true,extras={},onProgress=null){if(!portfolio?.packages?.length)throw Error('Upload at least one .dtsx package');let success=[],issues=[],skipped=[];
 for(let p of ordered()){if(!filter(p)){skipped.push(p.name);continue} $('global-state').textContent=`${op}: ${p.name}`;
 try{let res=await step(p,op,extras);success.push(p.name);if(onProgress)onProgress(p,res)}catch(e){issues.push(`${p.name}: ${e.message}`)}await refresh();}
 return {operation:op,completed:success.length,successful:success,skipped,issues};}
function finished(p){return p.glueStatus==='SUCCEEDED' && (p.state==='OUTPUTS_MATCH' || p.state==='GLUE_SUCCEEDED' || p.state==='PARTIAL_VALIDATION' || (p.validation && Object.values(p.validation).some(v=>v.status==='MATCH')));}
function needsAi(p){
 // Do not silently exclude eligible unsupported SCT packages because the
 // coordinator-based analyzer could not create quickAnalysis. The backend
 // makes the authoritative 25029/provenance/sidecar decision.
 if(finished(p)||p.pendingBaseHash||proposals.has(p.name))return false;
 if(p.unsupportedProcessAI&&['LOCAL_OUTPUT_GENERATED','LOCAL_PARITY_MATCH'].includes(p.processAIStatus))return false;
 if(p.processAIKind==='EXECUTE_PROCESS_25029'||p.unsupportedProcessAI)return true;
 if((p.blockers||[]).length>0)return true;
 if(p.quickAnalysis)return false; // ordinary successful analysis needs no AI
 return !!(p.sctImported||p.sctCompleted||p.state==='CONVERSION_REVIEW'||p.state==='REPAIR_BLOCKED');
}
function showProposals(){const area=$('review-list');area.replaceChildren();for(let [name,pr] of proposals){let wrap=document.createElement('div');wrap.className='review-diff';let h=document.createElement('h4');h.textContent=name;let pre=document.createElement('pre');pre.className='diff';pre.textContent=pr.diff||'No diff supplied — approval unavailable';wrap.append(h);if(pr.runtimePreflight){const note=document.createElement('p');note.textContent='Local preflight: '+pr.runtimePreflight.status+' — '+(pr.runtimePreflight.reason||pr.runtimePreflight.notice||pr.runtimePreflight.category||'');wrap.append(note)}wrap.append(pre);area.append(wrap)}$('review').classList.toggle('hidden',!proposals.size);$('approve-diffs').checked=false;}
async function recoverProposals(){
  proposals.clear();
  for(const p of portfolio?.packages||[]){
    if(!p.pendingBaseHash || finished(p))continue;
    try{
      const r=await fetch(`/api/artifact/${p.sessionId}/${p.unsupportedProcessAI?'process-ai-diff':'quick-ai-diff'}`);
      if(!r.ok)continue;
      const diff=await r.text();
      if(diff.trim() && (diff.startsWith('--- ') || diff.includes('\n+++ '))){
        proposals.set(p.name,{baseHash:p.pendingBaseHash,diff});
      }
    }catch(_){/* A missing historical diff cannot be auto-approved. */}
  }
  showProposals();
}
async function restore(){const p=await call('bulk-latest');if(p?.id){portfolio=p;render();await recoverProposals();report('upload-result',`Resumed portfolio ${p.id} (${p.packages.length} packages). Choose a new folder and click Start new migration to create a separate portfolio.`);}else{report('upload-result','No saved migrations to resume. Select a folder to start a new migration.');}}
function folderName(f){return f.webkitRelativePath||f.name;}
function resolveInput(packageFile, ref, allFiles){
  const target=ref.name.toLowerCase(),candidates=allFiles.filter(f=>f.name.toLowerCase()===target);
  if(!candidates.length)return {error:`${ref.name} was not found in selected source folder`};
  const packageDir=folderName(packageFile).replace(/\\/g,'/').split('/').slice(0,-1).join('/').toLowerCase();
  const original=String(ref.originalPath||'').replace(/\\/g,'/').toLowerCase();
  const suffix=original.split('/').filter(Boolean);
  const scored=candidates.map(f=>{
   const path=folderName(f).replace(/\\/g,'/').toLowerCase();
   let score=0;
   if(path.substring(0,path.lastIndexOf('/'))===packageDir)score+=100;
   for(let n=2;n<=Math.min(5,suffix.length);n++){
     const end=suffix.slice(-n).join('/');if(path.endsWith('/'+end))score=Math.max(score,20+n*5);
   }
   const pkgSegment=packageDir.split('/').pop();
   if(pkgSegment&&path.split('/').includes(pkgSegment))score+=5;
   return {f,score};
  }).sort((a,b)=>b.score-a.score);
  if(scored.length>1&&scored[0].score===scored[1].score)return {error:`Multiple ${ref.name} files match ${packageFile.name}; select a folder with unambiguous sources`};
  return {file:scored[0].f,method:scored[0].score>=100?'PACKAGE_DIRECTORY':scored[0].score>=30?'ORIGINAL_PATH_SUFFIX':'UNIQUE_FOLDER_FILENAME'};
}
$('upload').onclick=()=>wrapped(async()=>{
 let allFiles=[...$('source-folder').files].filter(f=>!f.name.startsWith('.'));
 let files=allFiles.filter(f=>/\.dtsx$/i.test(f.name));
 if(!files.length)throw Error('The selected folder contains no .dtsx packages');
 if(files.length>500)throw Error('Folder contains more than 500 packages');
 // Always create an isolated portfolio for a new folder upload. Never append to the restored portfolio.
 portfolio=await call('bulk-create');proposals.clear();showProposals();render();
 let issues=[],found=[],staged=[];
 const nonPackages=allFiles.filter(f=>!/\.dtsx$/i.test(f.name));
 for(let f of files){
  try{
   if(f.size>6_000_000)throw Error('SSIS file exceeds 6 MB');
   const path=folderName(f);
   let added=await call('bulk-add',{portfolioId:portfolio.id,fileName:f.name,relativePath:path,reuseMatching:true,contentBase64:await base64(f)});
   found.push({package:f.name,folderPath:path,reusedSession:!!added.reused,dependencies:added.dependencies,requiredInputs:added.inputReferences.map(r=>r.name)});
   // An Execute Process Task may depend on external source files not listed
   // as SSIS Flat File connection managers. Stage only filename-matched
   // script and CSV evidence; nothing is sent to Bedrock until approval.
   const supportFiles=nonPackages.filter(x=>/\.(ps1|csv)$/i.test(x.name));
   for(let sf of supportFiles){
     let role=/\.ps1$/i.test(sf.name)?'script':'input'; // Never infer independent SSIS baselines from filenames
     if(sf.size>(role==='script'?100_000:2_000_000))continue;
     try{await call('bulk-support',{portfolioId:portfolio.id,packageName:f.name,role,fileName:sf.name,contentBase64:await base64(sf)});}
     catch(e){if(role==='script' && /ExecuteProcess/.test(String(e.message)))issues.push(`${f.name}: ${e.message}`)}
   }
   for(let ref of added.inputReferences){
    const match=resolveInput(f,ref,nonPackages);
    if(match.error){issues.push(`${f.name}: ${match.error}`);continue;}
    const source=match.file;
    if(!/\.csv$/i.test(source.name)){issues.push(`${f.name}: ${source.name} is not a supported CSV source for automatic staging`);continue;}
    if(source.size>3_000_000){issues.push(`${f.name}: ${source.name} exceeds the 3 MB upload limit`);continue;}
    await call('bulk-input',{portfolioId:portfolio.id,packageName:f.name,fileName:source.name,relativePath:folderName(source),resolutionMethod:match.method,contentBase64:await base64(source)});
    staged.push({package:f.name,input:source.name,folderPath:folderName(source),method:match.method});
   }
  }catch(e){issues.push(`${folderName(f)}: ${e.message}`)}await refresh();
 }
 report('upload-result',{discoveredPackages:found.length,inputFilesStaged:staged.length,packages:found,stagedInputs:staged,issues,
    note:'This folder was uploaded to a new independent portfolio. The prior migration remains saved for explicit resume. Missing sources are not replaced with demo files.'});
 if(portfolio.packages.length)show(1);
});
$('restore').onclick=()=>wrapped(restore);
$('convert').onclick=()=>wrapped(async()=>{let r=await all('convert',p=>!p.sctCompleted);report('convert-result',r);if(r.completed)show(2)});
$('analyze').onclick=()=>wrapped(async()=>{let r=await all('analyze',p=>!finished(p)&&p.sctImported&&(!p.quickAnalysis||p.state==='REPAIR_BLOCKED'||p.state==='CONVERTED'));report('repair-result',{...r,notice:r.completed===0&&!r.issues.length?'No new analysis was run. Open Details beside a package to see its current status and existing artifacts; already-analyzed or completed packages are skipped.':'Analysis complete. Open Details in Package results to inspect individual package status.'});});
$('ai').onclick=()=>wrapped(async()=>{if(!$('ai-cost').checked||!$('ai-send').checked)throw Error('Approve Bedrock charges and screened source transmission');
 await recoverProposals();let r=await all('ai-propose',p=>needsAi(p),{},(p,x)=>{let v=x.result||{};if(v.status==='AI_PATCH_REVIEW_ONLY'&&v.baseHash&&v.diff)proposals.set(p.name,{baseHash:v.baseHash,diff:v.diff,runtimePreflight:v.runtimePreflight});});
 showProposals();report('repair-result',{...r,proposalsForReview:proposals.size,appVersion:'3.0.10-spark-column-repair',diagnostics:ordered().filter(p=>r.skipped.includes(p.name)).map(p=>({package:p.name,stage:p.state,sctCompleted:!!p.sctCompleted,sctImported:!!p.sctImported,hasAnalysis:!!p.quickAnalysis,blockers:(p.blockers||[]).length,pendingProposal:!!p.pendingBaseHash,alreadySucceeded:finished(p)})),notice:'Server-side remediation failures are listed under issues. If this version marker is missing, the browser is serving an older build.'});});
$('apply').onclick=()=>wrapped(async()=>{if(!proposals.size)throw Error('No proposals to approve');if(!$('approve-diffs').checked)throw Error('Review and approve the exact combined diff');
 let results=[],errors=[],validation=[];for(let p of ordered()){
  let pr=proposals.get(p.name);if(!pr || finished(p))continue;
  try{
   // Human approval remains mandatory. Never treat proposal generation as acceptance.
   let accepted=await step(p,'ai-accept',{baseHash:pr.baseHash,approveExactDiff:true});
   results.push(p.name);proposals.delete(p.name);await refresh();
   // Same workflow, no separate validation button. Only an approved genuine
   // unsupported-task candidate enters local Spark validation. Normal A/B
   // quick repairs keep their existing independent validator.
   let current=portfolio.packages.find(q=>q.name===p.name);
   if(current?.processAIKind==='EXECUTE_PROCESS_25029'){
    try{
     const checked=await step(current,'ai-local-validate');
     validation.push({package:p.name,status:checked.result?.status||checked.state,
       note:'Independent SSIS parity is only claimed when a trusted reference was supplied.'});
    }catch(e){validation.push({package:p.name,status:'LOCAL_VALIDATION_FAILED',reason:e.message});}
    await refresh();
   }
  }catch(e){errors.push(`${p.name}: ${e.message}`)}
 }
 showProposals();report('repair-result',{patchesApplied:results,validation,errors,notice:'Reviewed patches are applied only after approval. Local checks run automatically for unsupported tasks; failed or missing validation never permits Glue deployment. Normal packages retain their existing validation gates.'});});
$('deploy').onclick=()=>wrapped(async()=>{if(!$('deploy-approval').checked)throw Error('Approve deployment and AWS charges');
 const eligible=p=>!finished(p)&&!p.jobName&&((!(p.blockers||[]).length&&!!p.quickAnalysis) || p.unsupportedProcessAI || p.processAIKind==='EXECUTE_PROCESS_25029');
 // Send unsupported tasks to the server even if their proposal failed: the
 // backend reports an actionable prerequisite error instead of a silent skip.
 let aws=await all('aws',eligible);let verified=new Set(aws.successful);
 let r=await all('deploy',p=>eligible(p)&&verified.has(p.name));report('deploy-result',{aws,deploy:r,notice:'AI repairs deploy the exact approved locally tested code. Glue output generation and SSIS parity are reported separately.'});if(r.completed)show(4);});
$('run').onclick=()=>wrapped(async()=>{if(!$('run-approval').checked)throw Error('Approve Glue job charges');let r=await all('run',p=>!finished(p)&&!!p.jobName&&!['SUBMITTED','RUNNING','SUCCEEDED'].includes(p.glueStatus));report('run-result',r);});
$('poll').onclick=()=>wrapped(async()=>{let r=await all('poll',p=>!!p.runId && (p.glueStatus!=='SUCCEEDED'||(p.aiCloudOrigin&&!p.cloudOutputValidated)));report('run-result',r);});
$('validate').onclick=()=>wrapped(async()=>{let files=[...$('baselines').files];if(!files.length)throw Error('Select trusted reference CSVs');
 let entries=portfolio.packages.flatMap(p=>{
   const cloud=(p.aiCloudOrigin==='APPROVED_BEDROCK_SCT_25029' || p.processAIKind==='EXECUTE_PROCESS_25029')
       ? (p.cloudOutputs||[]).map(x=>x?.output).filter(n=>typeof n==='string'&&n.toLowerCase().endsWith('.csv')) : [];
   const names=cloud.length?cloud:(p.outputs||[]).filter(n=>typeof n==='string'&&n.toLowerCase().endsWith('.csv'));
   return [...new Set(names)].map(n=>({p,n}));
 });if(!entries.length)throw Error('No inspected CSV outputs have been registered. Run and check Glue status first.');let counts=new Map();for(let {n} of entries)counts.set(n.toLowerCase(),(counts.get(n.toLowerCase())||0)+1);
 let matches=[],issues=[];for(let {p,n} of entries){if(p.glueStatus!=='SUCCEEDED'){issues.push(`${p.name}/${n}: job not succeeded`);continue}
 let stem=p.name.replace(/\.dtsx$/i,''),alt=n.replace(/_SSIS(?=\.csv$)/i,''),common=counts.get(n.toLowerCase())===1;
 let candidates=[stem+'__'+n,stem+'__'+alt,...(common?[n,alt]:[])];let found=files.filter(f=>candidates.some(a=>a.toLowerCase()===f.name.toLowerCase()));
 if(found.length!==1){issues.push(`${p.name}/${n}: ${found.length?'ambiguous':'missing'} reference file`);continue}
 try{let r=await step(p,'validate',{outputName:n,contentBase64:await base64(found[0])});if(r.result?.status==='MATCH')matches.push(`${p.name}/${n}`);else issues.push(`${p.name}/${n}: ${r.result?.status||'UNVERIFIED'}`)}catch(e){issues.push(`${p.name}/${n}: ${e.message}`)}await refresh();}
 report('run-result',{matched:matches,unverified:issues,notice:'Only CSV versus supplied baseline is tested; no SQL parity is inferred.'});});
$('refresh').onclick=()=>wrapped(refresh);$('prev').onclick=()=>show(stage-1);$('next').onclick=()=>show(stage+1);
for(let [i,n] of titles.entries()){let b=document.createElement('button');b.textContent=`0${i+1}  ${n}`;b.onclick=()=>show(i);$('nav').append(b)}
render();show(0);restore().catch(e=>report('upload-result','Saved migrations could not be loaded: '+e.message)); // Show saved work; new folder always creates a separate portfolio.
})();