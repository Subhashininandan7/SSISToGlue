'use strict';
// Local read-only runtime inventory. Official install links are static and reviewed.
(() => {
  const byId = id => document.getElementById(id);
  const overlay = byId('runtime-overlay');
  const content = byId('runtime-results');
  const status = byId('runtime-status');
  const installLabels = {
    dotnet: 'Download .NET 8 SDK',
    python: 'Download Python',
    pyspark: 'PySpark installation guide',
    java: 'Download Temurin JDK 17',
    aws: 'Install AWS CLI v2',
    sct: 'Install AWS SCT',
    hadoop: 'Apache Spark documentation'
  };
  const expectedUrls = {
    dotnet: 'https://dotnet.microsoft.com/en-us/download/dotnet/8.0',
    python: 'https://www.python.org/downloads/windows/',
    pyspark: 'https://spark.apache.org/docs/latest/api/python/getting_started/install.html',
    java: 'https://adoptium.net/temurin/releases/?version=17',
    aws: 'https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html',
    sct: 'https://docs.aws.amazon.com/SchemaConversionTool/latest/userguide/CHAP_Installing.Procedure.html',
    hadoop: 'https://spark.apache.org/docs/latest/'
  };
  function show() { overlay.classList.remove('hidden'); byId('runtime-close').focus(); }
  function hide() { overlay.classList.add('hidden'); }
  function item(comp) {
    const row = document.createElement('div');
    row.className = 'runtime-component';
    const main = document.createElement('div');
    main.className = 'runtime-component-text';
    const name = document.createElement('strong'); name.textContent = comp.name;
    const detail = document.createElement('small'); detail.textContent = comp.detail;
    main.append(name, detail);
    const aside = document.createElement('div');
    aside.className = 'runtime-component-actions';
    const state = document.createElement('span');
    state.className = 'runtime-state ' + (comp.found ? 'runtime-found' : 'runtime-missing');
    state.textContent = comp.found ? 'Detected' : 'Needs setup';
    aside.append(state);
    if (!comp.found && expectedUrls[comp.id]) {
      const link = document.createElement('a');
      link.href = expectedUrls[comp.id]; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = installLabels[comp.id];
      aside.append(link);
    }
    row.append(main, aside);
    return row;
  }
  async function check() {
    content.replaceChildren();
    status.textContent = 'Checking this computer…';
    try {
      const resp = await fetch('/api/runtime/check', {cache:'no-store'});
      const data = await resp.json();
      if (!resp.ok) throw Error(data.error || 'Runtime check unavailable');
      byId('runtime-hadoop').value = data.hadoopHome || '';
      const summary = document.createElement('p');
      summary.textContent = `Local Spark readiness: ${data.localSparkReady ? 'Prerequisites detected' : 'Setup needed'}. This is a prerequisite check, not a Spark execution test.`;
      content.append(summary);
      for (const c of data.components || []) content.append(item(c));
      const paths = document.createElement('p');
      paths.className = 'runtime-paths';
      paths.textContent = `Per-user working folders:\nTEMP: ${data.temp}\nSpark: ${data.sparkLocal}`;
      content.append(paths);
      const note = document.createElement('p');
      note.className = 'hint'; note.textContent = data.notice;
      content.append(note);
      status.textContent = data.localSparkReady ? 'Local Spark prerequisites detected' : 'Runtime prerequisites need attention';
    } catch (e) {
      status.textContent = 'Runtime check failed';
      content.textContent = e.message || String(e);
    }
  }
  byId('runtime-open').addEventListener('click', () => { show(); void check(); });
  byId('runtime-close').addEventListener('click', hide);
  byId('runtime-recheck').addEventListener('click', () => void check());
  byId('runtime-save').addEventListener('click', async () => {
    try {
      const response = await fetch('/api/runtime/settings', {
        method:'POST',headers:{'Content-Type':'application/json','X-Demo-Request':'1'},
        body:JSON.stringify({hadoopHome:byId('runtime-hadoop').value.trim()})
      });
      const value = await response.json();
      if (!response.ok) throw Error(value.error || 'Could not save runtime settings');
      await check();
    } catch(e) { status.textContent = e.message || String(e); }
  });
  // First-run AWS wizard remains separate; can be opened independently.
})();
