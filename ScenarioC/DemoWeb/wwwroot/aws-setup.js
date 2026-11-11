"use strict";
// AWS setup is additive: all existing migration engine endpoints and actions remain unchanged.
(()=>{
  const $=id=>document.getElementById(id);
  const ids={profile:'aws-profile',region:'aws-region',s3Bucket:'aws-bucket',s3Prefix:'aws-prefix',glueRole:'aws-role',bedrockModel:'aws-model',loginMethod:'aws-login-method'};
  let saved=false, busy=false;
  let catalog=[];
  const overlay=$('aws-setup-overlay'), result=$('aws-setup-result'), pill=$('aws-connection-pill');
  const values=()=>Object.fromEntries(Object.entries(ids).map(([k,id])=>[k,$(id).value.trim()]));
  function selectModel(id, choices){
    const targets=[$('aws-model'),$('model')];
    for(const sel of targets){
      sel.replaceChildren();
      for(const c of choices){const opt=document.createElement('option');opt.value=c.id;opt.textContent=`${c.label} (${c.id})`;sel.appendChild(opt)}
      if(id && !choices.some(c=>c.id===id)){
        const existing=document.createElement('option');existing.value=id;existing.textContent=`${id} (previous selection — not verified in current catalog)`;sel.prepend(existing);
      }
      if(id)sel.value=id;
    }
  }
  async function refreshModels(){
    const profile=$('aws-profile').value.trim(),region=$('aws-region').value.trim();
    const r=await fetch(`/api/aws-setup/bedrock-models?profile=${encodeURIComponent(profile)}&region=${encodeURIComponent(region)}`,{cache:'no-store'});
    const response=await r.json();if(!r.ok)throw Error(response.error||'Cannot discover Bedrock models');
    const current=$('aws-model').value;catalog=response.choices||[];
    selectModel(current,catalog);
    $('aws-model-status').textContent=`${catalog.length} catalog entries found for ${region}. ${response.message}`;
    if(!response.ok)result.textContent=response.message;
  }
  function populate(d){for(const [k,id] of Object.entries(ids))$(id).value=d[k]??'';sync(d)}
  function sync(d){selectModel(d.bedrockModel || 'amazon.nova-lite-v1:0',catalog);$('profile').value=d.profile||'default';$('region').value=d.region||'ap-southeast-2';
    $('s3').value=d.s3Bucket?`s3://${d.s3Bucket}/${(d.s3Prefix||'').replace(/^\/+/, '')}`:'';
    $('role').value=d.glueRole||'';}
  function open(){overlay.classList.remove('hidden');$('aws-profile').focus()}
  function close(){overlay.classList.add('hidden')}
  async function request(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Request':'1'},body:JSON.stringify(body||{})});
    const v=await r.json();if(!r.ok)throw Error(v.error||'AWS setup request failed');return v;}
  async function save(){const x=values();const r=await request('/api/aws-setup',x);saved=true;sync(r.settings);result.textContent='Settings saved for this Windows user. You can now connect or test the AWS account.';pill.textContent='AWS not checked';return r;}
  async function task(fn){if(busy)return;busy=true;const buttons=overlay.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
    try{await fn()}catch(e){result.textContent=e.message||String(e);pill.textContent='AWS needs attention';}
    finally{busy=false;buttons.forEach(b=>b.disabled=false)}}
  $('aws-model').addEventListener('change',()=>{$('model').value=$('aws-model').value;saved=false;});
  $('model').addEventListener('change',()=>{$('aws-model').value=$('model').value;saved=false;});
  $('aws-region').addEventListener('change',()=>{$('aws-model-status').textContent='Region changed. Refresh models to discover region-specific choices.';});
  $('aws-refresh-models').onclick=()=>task(refreshModels);
  $('aws-save').onclick=()=>task(save);
  async function connect(){await save();const x=await request('/api/aws-setup/connect');result.textContent=x.message+' The selected AWS profile and region are used automatically.';pill.textContent='AWS sign-in in progress';}
  $('aws-connect').onclick=()=>task(connect);
  $('aws-reconnect').onclick=()=>task(connect);
  $('aws-test').onclick=()=>task(async()=>{
    if(!saved)await save();const x=await request('/api/aws-setup/test');
    if(!x.connected){result.textContent=x.message||'AWS authentication required';pill.textContent='AWS disconnected';return}
    pill.textContent=`AWS ${x.account} connected`;
    const checks=x.checks||{};
    result.textContent=`Connected: ${x.identity}\nAccount: ${x.account} | Region: ${x.region}\n`+
      Object.entries(checks).map(([k,v])=>`${k}: ${v.ok?'OK':'Not verified'} (${v.message})`).join('\n')+
      '\nCatalog/permission checks do not guarantee Bedrock model invocation or Glue deployment.';
  });
  $('aws-settings-button').onclick=open;$('aws-setup-close').onclick=close;
  // Only prefill from non-secret appsettings defaults or a per-user configuration file.
  fetch('/api/aws-setup',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('AWS setup unavailable');return r.json()}).then(x=>{
    saved=!!x.configured;populate(x.settings);refreshModels().catch(e=>{$('aws-model-status').textContent=e.message||'Model discovery unavailable';});if(!saved)open();
    else pill.textContent='AWS connection not checked';
  }).catch(e=>{result.textContent=e.message;open()});
})();
