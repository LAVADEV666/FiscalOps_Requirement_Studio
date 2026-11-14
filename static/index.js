'use strict';const $=s=>document.querySelector(s),input=$('#pdf'),zone=$('#dropZone'),status=$('#status'),progress=$('#progress'),go=$('#go'),ready=$('#fileReady');
const escapeHTML = value => String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let processing=false,completedSessionId='',finishProcessingMotion;
function say(text,state=''){status.className='status '+state;status.querySelector('span').textContent=text;$('#manualRecovery').classList.add('hidden')}
function clearFile(){if(processing)return;setProcessing(false);completedSessionId='';$('#openCompleted').hidden=true;$('#goLabel').textContent='Procesar requerimiento';input.value='';go.disabled=true;zone.classList.remove('loaded');ready.classList.add('hidden');$('#removeFile').classList.add('hidden');zone.querySelector('h2').textContent='Arrastra el PDF aquí';zone.querySelector(':scope > span').textContent='o haz clic para seleccionarlo';say('Listo para recibir un PDF')}
function choose(file){if(!file||processing)return;if(file.type!=='application/pdf'&&!file.name.toLowerCase().endsWith('.pdf')){clearFile();return say('El archivo seleccionado no es PDF.','error')}if(file.size>50*1024*1024){clearFile();return say('El PDF excede 50 MB.','error')}setProcessing(false);completedSessionId='';$('#openCompleted').hidden=true;$('#goLabel').textContent='Procesar requerimiento';const dt=new DataTransfer();dt.items.add(file);input.files=dt.files;go.disabled=false;zone.classList.add('loaded');ready.classList.remove('hidden');$('#removeFile').classList.remove('hidden');$('#fileName').textContent=file.name;$('#fileMeta').textContent=`${(file.size/1024/1024).toFixed(2)} MB · PDF listo para procesar`;zone.querySelector('h2').textContent='PDF preparado';zone.querySelector(':scope > span').textContent='Puede cambiarlo o iniciar el procesamiento';say('Archivo cargado correctamente','done')}
zone.onclick=e=>{if(!processing&&e.target!==input&&!e.target.closest('#removeFile'))input.click()};zone.onkeydown=e=>{if(!processing&&e.target===zone&&(e.key==='Enter'||e.key===' ')){e.preventDefault();input.click()}};['dragenter','dragover'].forEach(n=>zone.addEventListener(n,e=>{e.preventDefault();zone.classList.add('drag')}));['dragleave','drop'].forEach(n=>zone.addEventListener(n,e=>{e.preventDefault();zone.classList.remove('drag')}));zone.ondrop=e=>choose(e.dataTransfer.files[0]);input.onchange=()=>choose(input.files[0]);$('#changeFile').onclick=()=>{if(!processing)input.click()};$('#removeFile').onclick=e=>{e.stopPropagation();clearFile()};
function setProcessing(value){
    processing=value;
    if(value&&!finishProcessingMotion)finishProcessingMotion=window.FiscalMotion.begin();
    if(!value&&finishProcessingMotion){finishProcessingMotion();finishProcessingMotion=null;}
    go.disabled=value;
    go.setAttribute('aria-busy',String(value));
    $('#goLabel').textContent=value?'Procesando requerimiento…':'Procesar requerimiento';
    $('.home-flow-content').classList.toggle('hidden',value);
    $('.home-job').classList.toggle('hidden',!value);
    progress.classList.toggle('hidden',!value);
    if(value){
        progress.removeAttribute('aria-valuenow');
        progress.firstElementChild.style.removeProperty('width');
        $('#jobPercent').textContent='—';
        $('#jobHeadline').textContent='Preparando el PDF';
    }
}
async function refreshHybridStatus(){
    const box=$('#hybridStatus'),state=$('#ollamaState'),model=$('#ollamaModel'),toggle=$('#ollamaEnabled'),selector=$('#ollamaModelSelect');
    if(!box||!state||!model)return;
    try{
        const response=await fetch('/api/ollama/status',{cache:'no-store'}),result=await response.json();
        const ready=Boolean(result.available&&result.model_available);
        box.dataset.state=ready?'ready':'warn';
        box.querySelector('span').textContent=ready?'Ollama disponible · IA local lista':(result.enabled?'Ollama activado · modelo no disponible':'Ollama desactivado · flujo determinista disponible');
        state.textContent=ready?'Disponible':(result.enabled?'Revisar':'Desactivado');
        model.textContent=result.model||'—';
        if(toggle)toggle.checked=Boolean(result.enabled);
        if(selector){
            const models=result.supported_models||[];
            selector.innerHTML=models.map(value=>`<option value="${escapeHTML(value)}">${escapeHTML(value)}</option>`).join('');
            selector.value=result.model||models[0]||'';
        }
    }catch(error){
        box.dataset.state='warn';box.querySelector('span').textContent='No se pudo consultar Ollama · el flujo local continúa';state.textContent='No disponible';model.textContent='—';
    }
}
$('#saveOllamaSettings')?.addEventListener('click',async()=>{
    const message=$('#ollamaConfigMessage'),button=$('#saveOllamaSettings');
    button.disabled=true;message.textContent='Guardando configuración local…';
    try{
        const response=await fetch('/api/ollama/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:Boolean($('#ollamaEnabled')?.checked),model:$('#ollamaModelSelect')?.value})}),result=await response.json();
        if(!response.ok)throw new Error(result.detail||'No fue posible guardar la configuración.');
        message.textContent='Configuración aplicada a esta sesión.';await refreshHybridStatus();
    }catch(error){message.textContent=String(error.message||error)}finally{button.disabled=false}
});
refreshHybridStatus();
async function startProcessing(manual=false){
    const file=input.files[0];
    if(!file||processing)return;
    setProcessing(true);
    say('Preparando el PDF…','working');
    const form=new FormData();
    form.append('file',file);
    if(manual)form.append('manual_review','true');
    try {
        const response=await fetch('/api/process-async',{method:'POST',body:form,cache:'no-store'}), result=await response.json();
        if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:result.detail?.message||'No fue posible iniciar');
        await watchJob(result.task_id);
    } catch(error) {
        setProcessing(false);
        say(error.message,'error');
        if(error.manualAvailable)$('#manualRecovery').classList.remove('hidden');
    }
}
go.onclick=()=>completedSessionId?location.assign('/audit?job='+encodeURIComponent(completedSessionId)):startProcessing();
$('#manualRecovery').onclick=()=>startProcessing(true);
async function watchJob(taskId){
    for(;;){
        const response=await fetch(`/api/jobs/${taskId}`,{cache:'no-store'}), job=await response.json();
        if(!response.ok)throw new Error(job.detail||'No se pudo consultar el progreso.');
        if(job.status==='failed'){
            const error=new Error(job.error?.message||'El procesamiento terminó con error.');
            error.manualAvailable=job.error?.type==='NoRequirementDetected';
            throw error;
        }
        if(job.status==='cancelled')throw new Error('Procesamiento cancelado.');
        const percent=Number(job.progress)||0, complete=job.status==='completed';
        const label=complete?'Abriendo el expediente…':job.message||job.stage||'Procesando el PDF';
        progress.setAttribute('aria-valuenow',percent);
        progress.firstElementChild.style.width=percent+'%';
        $('#jobPercent').textContent=percent+'%';
        $('#jobHeadline').textContent=label;
        say(label+' · '+percent+'%',complete?'done':'working');
        if(complete){
            completedSessionId=job.result.session_id;
            finishProcessingMotion?.();finishProcessingMotion=null;
            processing=false;go.disabled=false;go.setAttribute('aria-busy','false');$('#goLabel').textContent='Abrir expediente';
            const open=$('#openCompleted');open.hidden=false;open.onclick=()=>location.assign('/audit?job='+encodeURIComponent(completedSessionId));
            if(!$('#home-import').hidden&&!document.querySelector('dialog[open]'))location.assign(`/audit?job=${job.result.session_id}`);
            else {$('#homeStatus').textContent='PDF procesado · Tu expediente está listo';homeMessage('Procesamiento terminado. Abre el expediente cuando estés listo.')} 
            return;
        }
        await new Promise(resolve=>setTimeout(resolve,500));
    }
}
