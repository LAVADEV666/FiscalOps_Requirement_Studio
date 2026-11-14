'use strict';
const $=s=>document.querySelector(s);const panel=id=>document.getElementById(id);const job=new URLSearchParams(location.search).get('job');let data=null,page=1,zoom=1,selected=null,dirty=false,undoStack=[],redoStack=[];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const event=(action,rid='',fid='',before='',after='')=>({timestamp:new Date().toISOString(),action,requirement_id:rid,fragment_id:fid,before,after,actor:'local_user'});
function toast(message,type='ok'){const t=$('#toast');t.textContent=message;t.className=type;t.style.display='block';clearTimeout(t._timer);t._timer=setTimeout(()=>t.style.display='none',2600)}
function fatal(error){$('#loadingOverlay').classList.add('hidden');$('#fatalError').classList.remove('hidden');$('#fatalText').textContent=error?.message||String(error)}

let conflicted=false;
async function api(url,options={}) {
    const response=await fetch(url,{cache:'no-store',...options});
    if(response.ok)return response;
    let detail;
    try{detail=(await response.json()).detail}catch{}
    const error=new Error(typeof detail==='string'?detail:detail?.message||'HTTP '+response.status);
    error.detail=detail;
    if(detail?.code==='REVISION_CONFLICT')showConflict();
    throw error;
}
function showConflict(){
    conflicted=true;
    if($('#exportDialog').open)$('#exportDialog').close();
    setSaveState('Conflicto de revisión','error');
    $('#revisionConflict').classList.remove('hidden');
}
async function init(){
    const finishWorkspaceMotion=window.FiscalMotion.begin();
    try {
        if(!job)throw new Error('Falta el identificador de sesión.');
        data=await(await api(`/api/workspace/${job}?v=${Date.now()}`)).json();
        normalize();migrateWordEditor();bindStatic();renderAll();
        const lastTab=sessionStorage.getItem('fiscalops.tab.'+job);
        if(lastTab&&panel(lastTab+'Tab'))activateTab(lastTab);
        $('#loadingMessage').textContent='Preparando el visor del PDF';
        await showPage(1);
        $('#loadingOverlay').classList.add('is-leaving');
        $('#loadingOverlay').setAttribute('aria-hidden','true');
        $('#split').setAttribute('aria-busy','false');
        document.querySelectorAll('.topbar, .case-bar, #split').forEach(node=>node.inert=false);
        if(!data.points.length && data.diagnostics?.strategy==='manual_ocr')manualOcr.start();
    }catch(error){fatal(error)}
    finally{finishWorkspaceMotion()}
}
function normalize(){data.workspace_revision=data.workspace_revision||0;data.points=data.points||[];data.fragments=data.fragments||[];data.assets=data.assets||[];data.audit_log=data.audit_log||[];data.validation=data.validation||{alerts:[],metrics:{},completeness:0};data.metadata_validation=data.metadata_validation||{fields:{}};data.compliance_matrix=data.compliance_matrix||{schema_version:'fiscalops.compliance.v1',rows:[],metrics:{}};data.document=data.document||{schema_version:'fiscalops.document.v1',revision:1,sections:[]};data.document_inspection=data.document_inspection||{pages:[],classification_counts:{}};data.ocr_decisions=data.ocr_decisions||{pages:[],summary:{}};data.reconstruction=data.reconstruction||{pages:[],text:''};data.cross_validation=data.cross_validation||{metrics:{},discrepancies:[],critical_fields:{}};data.fiscal_interpretation=data.fiscal_interpretation||{};for(const p of data.points){p.requirement_id=p.requirement_id||`REQ-${String(p.number).padStart(3,'0')}`;p.fragment_ids=p.fragment_ids||[];p.asset_ids=p.asset_ids||[];p.original_text=p.original_text||p.text;p.version=p.version||1;p.status=p.status||'detected'}}

function syncPaneControls() {
    const split = $('#split');
    $('#maxPdf').setAttribute('aria-pressed',split.classList.contains('max-left'));
    $('#maxEditor').setAttribute('aria-pressed',split.classList.contains('max-right'));
    $('#wordFullscreenBtn')?.setAttribute('aria-pressed',split.classList.contains('max-right'));
    applyZoom();
}
function bindStatic() {
    const split=$('#split'), divider=$('#gutter');
    document.body.dataset.density=localStorage.getItem('fiscalops.density')||'compact';
    const switchPane=value=>{
        split.dataset.mobilePane=value;
        split.classList.remove('max-left','max-right');
        document.querySelectorAll('[data-mobile-pane]').forEach(button=>{if(button.tagName==='BUTTON')button.setAttribute('aria-pressed',String(button.dataset.mobilePane===value))});
        localStorage.setItem('fiscalops.mobilePane',value);syncPaneControls();
    };
    document.querySelectorAll('button[data-mobile-pane]').forEach(button=>button.onclick=()=>switchPane(button.dataset.mobilePane));
    switchPane(localStorage.getItem('fiscalops.mobilePane')==='pdf'?'pdf':'editor');
    $('#metricsToggle').onclick=()=>{
        const expanded=document.body.dataset.showMetrics!=='true';
        document.body.dataset.showMetrics=String(expanded);
        $('#metricsToggle').setAttribute('aria-expanded',String(expanded));
    };
    const focus=(kind)=>{split.classList.toggle(kind);split.classList.remove(kind==='max-left'?'max-right':'max-left');syncPaneControls()};
    const resize=(percent)=>{const value=Math.max(28,Math.min(61,percent));split.style.setProperty('--pdf-share',value+'%');divider.setAttribute('aria-valuenow',Math.round(value));localStorage.setItem('fiscalops.pdfShare',value);applyZoom()};
    const saved=Number(localStorage.getItem('fiscalops.pdfShare'));
    if(saved)resize(saved);
    $('#prev').onclick=()=>showPage(page-1).catch(e=>toast(e.message,'warn'));
    $('#next').onclick=()=>showPage(page+1).catch(e=>toast(e.message,'warn'));
    $('#zoomIn').onclick=()=>setZoom(zoom+.15);
    $('#zoomOut').onclick=()=>setZoom(zoom-.15);
    $('#zoomLabel').onclick=()=>setZoom(1);
    $('#saveBtn').onclick=()=>save();
    $('#wordBtn').onclick=openExport;
    $('#downloadWord').onclick=()=>{
        const template=$('#exportTemplate').value||null;
        download('/api/export',template?'Contestacion_FiscalOps_Plantilla.docx':'Contestacion_FiscalOps.docx',template);
    };
    $('#manageTemplates').onclick=()=>{$('#exportDialog').close();activateTab('templates')};
    $('#backupBtn').onclick=async()=>{if(!dirty||await save())location.assign('/api/workspace/'+job+'/backup')};
    $('#backupsHomeBtn').onclick=async()=>{if(!dirty||await save())location.assign('/#backups')};
    $('#managedBackupBtn').onclick=async()=>{
        if(dirty&&!await save())return;
        const button=$('#managedBackupBtn');button.disabled=true;
        try{await api('/api/backups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job})});toast('Resguardo guardado. Consúltalo en Inicio → Resguardos.');button.closest('details').open=false}
        catch(error){toast(error.message,'warn')}finally{button.disabled=false}
    };
    $('#conflictCopy').onclick=()=>{
        saveBlob(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),'FiscalOps_Mis_Cambios.json');
    };
    $('#conflictReload').onclick=()=>{if(!dirty||confirm('¿Abrir la última versión guardada? Los cambios locales de esta pestaña se descartarán.')){dirty=false;location.reload()}};
    $('#jsonBtn').onclick=()=>download('/api/export-json','Auditoria_FiscalOps.json');
    $('#previewBtn').onclick=()=>activateTab('preview');
    $('#undo').onclick=undo;$('#redo').onclick=redo;
    $('#maxPdf').onclick=()=>focus('max-left');
    $('#maxEditor').onclick=()=>focus('max-right');
    const tabs=[...document.querySelectorAll('.editor-tabs button')];
    tabs.forEach((button,index)=>{
        button.onclick=()=>activateTab(button.dataset.tab);
        button.onkeydown=e=>{
            const offset={ArrowLeft:-1,ArrowRight:1}[e.key];
            if(!offset)return;
            e.preventDefault();
            const target=tabs[(index+offset+tabs.length)%tabs.length];
            activateTab(target.dataset.tab);target.focus();
        };
    });
    divider.onpointerdown=e=>divider.setPointerCapture(e.pointerId);
    divider.onpointermove=e=>{
        if(!divider.hasPointerCapture(e.pointerId))return;
        const rect=split.getBoundingClientRect();
        resize(100*(e.clientX-rect.left)/rect.width);
    };
    divider.onkeydown=e=>{
        if(!['ArrowLeft','ArrowRight','Home'].includes(e.key))return;
        e.preventDefault();
        resize(e.key==='Home'?40:Number(divider.getAttribute('aria-valuenow'))+(e.key==='ArrowLeft'?-3:3));
    };
    new ResizeObserver(applyZoom).observe($('#pdfScroll'));
    window.addEventListener('keydown',e=>{
        if(e.defaultPrevented||e.target.closest?.('dialog'))return;
        if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();save()}
        if(e.key==='Escape'&&manualOcr.cancel())return;
        if(e.key==='Escape'&&(split.classList.contains('max-left')||split.classList.contains('max-right'))){
            split.classList.remove('max-left','max-right');syncPaneControls();
        }
    });
    window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
}

function renderAll() {
    const metadata=data.metadata_validation.fields||{}, fields=Object.values(metadata);
    const avg=fields.reduce((sum,field)=>sum+Number(field.confidence||0),0)/Math.max(1,fields.length);
    $('#confidence').textContent=Math.round(avg*100)+'%';
    $('#complete').textContent=(data.validation.completeness||0)+'%';
    $('#assetCount').textContent=data.assets.length;
    $('#docType').textContent=({native:'Digital',mixed:'Mixto',scanned:'Escaneado'})[data.document_type]||'PDF';
    $('#caseTitle').textContent=metadata.taxpayer_name?.valid?metadata.taxpayer_name.value:'Expediente fiscal';
    window.CompanyIdentity.mount($('#caseCompanyIdentity'),expedientRfc(),{registeredOnly:true});
    $('#caseDetail').textContent=`${data.pages} ${data.pages===1?'página':'páginas'} · ${data.points.length} ${data.points.length===1?'numeral':'numerales'}`;
    renderRequirements();renderVisuals();renderHybrid();renderHybridComparison();
    if(!$('#previewTab').classList.contains('hidden'))renderPreview();
    renderMetadata();
}

function activateTab(name) {
    const target=panel(name+'Tab');
    if(!target)return toast('Módulo no disponible','warn');
    const split=$('#split');
    if(split.classList.contains('max-left')){
        split.classList.remove('max-left');
        syncPaneControls();
    }
    sessionStorage.setItem('fiscalops.tab.'+job,name);
    document.querySelectorAll('.editor-tabs button').forEach(button=>{
        const current=button.dataset.tab===name;
        button.classList.toggle('active',current);
        button.setAttribute('aria-selected',current);
        button.tabIndex=current?0:-1;
    });
    document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('hidden',t!==target));
    if(name==='preview')renderPreview();
    if(name==='requirements')renderRequirements();
    if(name==='hybrid'){renderHybrid();renderHybridComparison();}
    if(name==='templates')setupTemplateLibrary(target,expedientRfc());
    $('#editorScroll').scrollTop=0;
}


function renderRequirements() {
    $('#requirementsTab').innerHTML=data.points.length?data.points.map(p=>{
        const id=esc(p.requirement_id), pages=p.page_start===p.page_end?`Página ${p.page_start}`:`Páginas ${p.page_start}–${p.page_end}`;
        return `<article class="req-card ${selected===p.requirement_id?'active':''}" id="card-${id}" data-id="${id}">
            <div class="req-head"><div class="req-title"><span>${String(p.number).padStart(2,'0')}</span><div><b>Numeral ${p.number}</b><div class="req-meta">${pages}</div></div></div>
            <button class="icon-action" data-goto="${id}">${desktopIcon('arrow-up-right')} Ver en PDF</button></div>
            <textarea data-text="${id}" aria-label="Texto del numeral ${p.number}">${esc(p.text)}</textarea>
            <div class="req-actions"><button data-restore="${id}">Restaurar original</button></div>
        </article>`;
    }).join(''):'<div class="empty ocr-empty"><b>La lectura inicial no encontró numerales.</b><p>Marca una zona del PDF para recuperar el texto o capturarlo manualmente.</p><button id="recoverOcr" class="soft-button icon-action" type="button">'+desktopIcon('scan')+' Empezar lectura por zonas</button></div>';
    $('#recoverOcr')?.addEventListener('click',()=>{
        if($('#split').classList.contains('max-right')){
            $('#split').classList.remove('max-right');
            syncPaneControls();
        }
        manualOcr.start();
    });
    document.querySelectorAll('[data-goto]').forEach(button=>button.onclick=()=>goRequirement(button.dataset.goto));
    document.querySelectorAll('[data-restore]').forEach(button=>button.onclick=()=>restore(button.dataset.restore));
    document.querySelectorAll('[data-text]').forEach(input=>{
        input.onfocus=()=>snapshot();
        input.oninput=()=>editText(input.dataset.text,input.value);
    });
}

function renderVisuals() {
    const target=$('#visualsTab');
    if(!data.assets.length){
        target.innerHTML='<div class="empty">Este PDF no contiene tablas ni imágenes detectadas.</div>';
        return;
    }
    target.innerHTML=`<div class="visual-toolbar"><b>${data.assets.length} ${data.assets.length===1?'elemento detectado':'elementos detectados'}</b><button data-all="1">Incluir todos</button><button data-all="0">Excluir todos</button></div><div class="asset-grid">${data.assets.map(item=>{
        const id=esc(item.asset_id), included=item.include!==false;
        const editable=item.type==='table'&&item.rows?.length;
        const mode=editable?`<select data-mode="${id}" aria-label="Formato de exportación"><option value="editable" ${item.mode==='editable'?'selected':''}>Tabla editable</option><option value="image" ${item.mode==='image'?'selected':''}>Recorte del PDF</option></select>`:'';
        return `<article class="asset-card ${included?'':'excluded'}">
            <img loading="lazy" src="/api/asset/${job}/${encodeURIComponent(item.file)}" alt="${esc(item.caption)}">
            <div><b>${item.type==='table'?'Tabla':'Imagen'} · página ${item.page}</b>
            <label><input type="checkbox" data-include="${id}" ${included?'checked':''}> Incluir en Word</label>${mode}
            <input data-caption="${id}" aria-label="Pie de imagen o tabla" value="${esc(item.caption)}">
            <button class="icon-action" data-page="${item.page}">${desktopIcon('arrow-up-right')} Ver en PDF</button></div>
        </article>`;
    }).join('')}</div>`;
    target.querySelectorAll('[data-all]').forEach(button=>button.onclick=()=>setAllAssets(button.dataset.all==='1'));
    target.querySelectorAll('[data-include]').forEach(input=>input.onchange=()=>{
        snapshot();asset(input.dataset.include).include=input.checked;markDirty();renderVisuals();renderPreview();
    });
    target.querySelectorAll('[data-mode]').forEach(input=>input.onchange=()=>{
        snapshot();asset(input.dataset.mode).mode=input.value;markDirty();renderPreview();
    });
    target.querySelectorAll('[data-caption]').forEach(input=>input.onchange=()=>{
        snapshot();asset(input.dataset.caption).caption=input.value;markDirty();renderPreview();
    });
    target.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>showSourcePage(Number(button.dataset.page)));
}
function asset(id){return data.assets.find(a=>a.asset_id===id)}function setAllAssets(include){snapshot();data.assets.forEach(a=>a.include=include);markDirty();renderVisuals();renderPreview()}

function renderHybrid(){
    const target=$('#hybridTab');if(!target)return;
    const inspection=data.document_inspection||{}, decisions=data.ocr_decisions||{}, validation=data.cross_validation||{}, interpretation=data.fiscal_interpretation||{};
    const counts=inspection.classification_counts||{}, summary=decisions.summary||{}, metrics=validation.metrics||{};
    const decisionByPage=new Map((decisions.pages||[]).map(item=>[Number(item.page),item]));
    const pages=inspection.pages||[];
    target.innerHTML=`<div class="hybrid-report"><div class="data-hero"><span class="eyebrow">TRAZABILIDAD · DOCUMENT INTELLIGENCE</span><h3>Inspección y validación del documento</h3><p>La lectura conserva el original y separa evidencia nativa, PaddleOCR, reintentos y revisión humana.</p></div><div class="hybrid-report-grid"><div><b>${inspection.inspected_pages||0}/${inspection.total_pages||0}</b><span>Páginas inspeccionadas</span></div><div><b>${summary.full_page_ocr||0}</b><span>Páginas OCR completo</span></div><div><b>${summary.mixed_regions||0}</b><span>Páginas mixtas / regiones</span></div><div><b>${metrics.discrepancy_count||0}</b><span>Incidencias</span></div><div><b>${metrics.critical_fields_validated||0}%</b><span>Campos críticos validados</span></div><div><b>${metrics.reference_available?'Medido':'No declarado'}</b><span>Fidelidad</span></div></div><div class="hybrid-report-note">Ollama: ${esc(interpretation.ollama?.used?interpretation.ollama.model:'no utilizado')} · ${esc(interpretation.ollama?.reason||'interpretación determinista revisable')}</div><div class="hybrid-page-list">${pages.map(item=>{const decision=decisionByPage.get(Number(item.page))||{};return `<div class="hybrid-page-row"><b>Página ${item.page}</b><span>${esc(item.page_type||'—')}</span><span>${esc(decision.action||'—')}</span><span>${Math.round(Number(item.quality_score||0)*100)}% calidad</span><small>${esc((decision.source_priority||[]).join(' · '))}${decision.human_review_required?' · Revisión humana':''}</small></div>`}).join('')||'<div class="empty">No hay inspección guardada para este expediente.</div>'}</div></div>`;
}

function renderHybridComparison(){
    const target=$('#hybridTab');if(!target)return;
    const inspectionPages=data.document_inspection?.pages||[], reconstructionPages=data.reconstruction?.pages||[];
    target.querySelectorAll('.hybrid-page-row').forEach((row,index)=>{
        const inspected=inspectionPages[index]||{}, reconstructed=reconstructionPages[index]||{};
        const nativeText=String(inspected.native_text||((inspected.page_type==='DIGITAL_TEXT')?reconstructed.text||'':''));
        const ocrBlocks=[...(reconstructed.blocks||[]),...(reconstructed.supplemental_blocks||[])].filter(block=>block.source!=='PDF_NATIVE');
        const ocrText=ocrBlocks.map(block=>block.text||'').filter(Boolean).join('\n');
        if(!nativeText&&!ocrText)return;
        const details=document.createElement('details');details.className='hybrid-compare';
        details.innerHTML=`<summary>Comparar texto nativo y OCR</summary><div class="hybrid-compare-grid"><section><h4>Texto nativo</h4><pre>${esc(nativeText||'No disponible')}</pre></section><section><h4>OCR / reconstrucción suplementaria</h4><pre>${esc(ocrText||'No se ejecutó OCR en esta página')}</pre></section></div>`;
        row.appendChild(details);
    });
}

function renderMetadata() {
    const fields=data.metadata_validation.fields||{};
    const groups={'Identificación':['taxpayer_name','rfc','office','expedient','reference','control'],'Fechas y plazo':['date','notification_date','deadline'],'Solicitud':['tax','period','amount','request_type'],'Autoridad':['authority','administrative_unit'],'Privacidad':['legal_representative']};
    for(const [key,name] of [['rfc','RFC'],['office','Número de oficio']]){
        fields[key]??={name,value:'',valid:false,source:'manual',confidence:0};
    }
    data.metadata_validation.fields=fields;
    const target=$('#metadataTab');
    target.innerHTML='<div class="data-hero"><h3>Datos del expediente</h3><p>Las plantillas se buscan con el RFC de este expediente.</p></div>'+Object.entries(groups).map(([title,keys])=>
        `<section class="data-group"><h4>${title}</h4>${keys.filter(key=>fields[key]).map(key=>{
            const f=fields[key];
            return `<div class="data-field ${!f.valid?'bad':f.confidence<.9?'review':''}"><label for="field-${key}"><b>${esc(f.name)}</b></label>
                <input id="field-${key}" data-field="${key}" value="${esc(f.value)}">
                <small>${esc(f.source)} · ${esc(f.message||'')}</small></div>`;
        }).join('')}</section>`).join('');
    target.querySelectorAll('[data-field]').forEach(input=>input.onchange=()=>{
        snapshot();
        const field=fields[input.dataset.field];
        field.value=input.value;delete field.reviewed_value;
        markDirty();
        if(!$('#previewTab').classList.contains('hidden'))renderPreview();
    });
}

function snapshot(){undoStack.push(JSON.stringify(data));if(undoStack.length>30)undoStack.shift();redoStack=[]}function markDirty(){dirty=true;changeCount++;if(conflicted)return;setSaveState('Cambios pendientes','pending');clearTimeout(saveTimer);saveTimer=setTimeout(()=>autosave(),2200)}
function editText(id,value){const p=data.points.find(x=>x.requirement_id===id);if(!p||p.text===value)return;p.text=value;p.status='review';setCanonicalText(id,value);p.version++;markDirty()}
function restore(id){snapshot();const p=data.points.find(x=>x.requirement_id===id),before=p.text;p.text=p.original_text;p.status='review';setCanonicalText(id,p.text);p.version++;data.audit_log.push(event('TEXT_RESTORED',id,p.fragment_ids[0]||'',before,p.text));markDirty();renderAll()}
function setCanonicalText(id,text) {
    const block=data.document.sections.find(s=>s.requirement_id===id)?.blocks.find(b=>b.type==='requirement_text');
    if(block){block.text=text;delete block.paragraphs;}
}
function goRequirement(id){
    selected=id;
    const point=data.points.find(x=>x.requirement_id===id);
    showSourcePage(point.page_start);
}
function showSourcePage(number){
    const split=$('#split');
    if(split.classList.contains('max-right')){
        split.classList.remove('max-right');
        syncPaneControls();
    }
    showPage(number).catch(error=>toast(error.message,'warn'));
}
function focusCard(id,scroll=true){
    selected=id;
    document.querySelectorAll('.req-card').forEach(c=>c.classList.toggle('active',c.dataset.id===id));
    document.querySelectorAll('.highlight').forEach(h=>h.classList.toggle('active',h.dataset.id===id));
    if(scroll){
        activateTab('requirements');
        $(`#card-${id}`)?.scrollIntoView({block:'center'});
    }
}

let pageRequest=0;
async function showPage(n) {
    const desired=Math.max(1,Math.min(data.pages,n)), token=++pageRequest, image=new Image();
    const stage=$('#pageStage'), loading=$('#pageLoading');
    stage.classList.remove('page-ready');
    loading.classList.remove('hidden');
    image.src='/api/page/'+job+'/'+desired;
    try {
        await image.decode();
    } catch {
        if(token!==pageRequest)return;
        throw new Error('No se pudo mostrar la página '+desired+' del PDF.');
    } finally {
        if(token===pageRequest)loading.classList.add('hidden');
    }
    if(token!==pageRequest)return;
    page=desired;
    $('#pageImage').src=image.src;
    $('#pageImage').alt='PDF original · página '+page;
    $('#pageLabel').textContent=page+' / '+data.pages;
    $('#prev').disabled=page===1;$('#next').disabled=page===data.pages;
    $('#pdfScroll').scrollTop=0;
    applyZoom();
    renderOverlay();
    manualOcr.pageChanged();
    stage.classList.add('page-ready');
}
function setZoom(value){zoom=Math.max(.5,Math.min(2.5,value));applyZoom()}
function applyZoom(){
    const viewport=$('#pdfScroll'),width=viewport.clientWidth;
    if(!width)return;
    $('#pageStage').style.width=Math.max(80,Math.min(width-32,760)*zoom)+'px';
    $('#zoomLabel').textContent=Math.round(zoom*100)+'%';
}

function renderOverlay(){const ov=$('#overlay');ov.innerHTML='';for(const f of data.fragments.filter(x=>x.page===page)){const b=f.bbox,s=f.page_size,d=document.createElement('button');d.className='highlight '+(f.method==='manual_ocr'?'manual':f.confidence<.8?'low':'');d.dataset.id=f.requirement_id;Object.assign(d.style,{left:100*b.x0/s.width+'%',top:100*b.y0/s.height+'%',width:100*(b.x1-b.x0)/s.width+'%',height:100*(b.y1-b.y0)/s.height+'%'});d.title=`${f.requirement_id} · ${f.method==='manual_ocr'?'Zona de OCR manual':Math.round(f.confidence*100)+'%'}`;d.onclick=()=>focusCard(f.requirement_id,true);ov.appendChild(d)}if(selected)focusCard(selected,false)}

let saveFlight, saveTimer, changeCount=0;
function setSaveState(text,state) {
    const label=$('#saveState');label.textContent=text;label.dataset.state=state;
    const compact=$('#mobileSaveState');
    compact.textContent=({pending:'Pendiente',working:'Guardando',saved:'Guardado',error:'Revisar'})[state]||text;
    compact.title=text;compact.dataset.state=state;
}
async function save(silent=false) {
    while(saveFlight){
        if(!await saveFlight)return false;
    }
    if(conflicted)return false;
    if(!data||!dirty){
        if(!silent)toast('El expediente está al día');
        return true;
    }
    const revision=changeCount, entry=event(silent?'WORKSPACE_AUTOSAVED':'WORKSPACE_SAVED');
    setSaveState('Guardando…','working');
    const payload=JSON.stringify({job_id:job,data,event:entry});
    saveFlight=(async()=>{
        try {
            const result=await(await api('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:payload})).json();
            data.workspace_revision=result.workspace_revision;
            data.audit_log.push(entry);
            if(revision===changeCount){
                dirty=false;data.validation=result.validation;
                $('#complete').textContent=result.validation.completeness+'%';
                setSaveState('Guardado localmente','saved');
            }else{
                setSaveState('Cambios pendientes','pending');
                clearTimeout(saveTimer);saveTimer=setTimeout(()=>autosave(),1200);
            }
            if(!silent)toast('Expediente guardado');
            return true;
        }catch(error){
            if(!conflicted)setSaveState('Guardado pendiente','error');
            if(!silent)toast(error.message,'warn');
            return false;
        }
    })();
    try{return await saveFlight}finally{saveFlight=null}
}
function saveBlob(blob,name) {
    const link=document.createElement('a');
    link.href=URL.createObjectURL(blob);link.download=name;link.click();
    setTimeout(()=>URL.revokeObjectURL(link.href),1000);
}
function expedientRfc() {
    return String(data.metadata_validation.fields?.rfc?.value||'').trim().toUpperCase();
}

async function openExport() {
    if(dirty&&!await save(true))return toast('Guarda el expediente antes de exportar.','warn');
    if(conflicted)return;
    const dialog=$('#exportDialog'), summary=$('#exportSummary'), select=$('#exportTemplate'), button=$('#downloadWord');
    select.replaceChildren(new Option('Formato estándar',''));
    summary.textContent='Buscando plantillas…';
    button.disabled=true;
    if(!dialog.open)dialog.showModal();
    const rfc=expedientRfc();
    try {
        if(!validTemplateRfc(rfc)){
            summary.textContent='Captura el RFC en Datos para usar una plantilla.';
            return;
        }
        const {templates}=await(await api(templateUrl(rfc))).json();
        for(const item of templates){
            const option=new Option(item.name+(item.configured?'':' · Sin plantilla'),item.id);
            option.disabled=!item.configured;
            select.add(option);
        }
        summary.textContent=templates.some(item=>item.configured)?'Elige el tipo de requerimiento para '+rfc+'.':'Todavía no hay plantillas para '+rfc+'.';
    }catch(error){summary.textContent=error.message}
    finally{button.disabled=false}
}

let exporting=false;
async function download(url,name,template_id=null){
    if(exporting||conflicted)return;
    exporting=true;
    const button=$('#downloadWord');
    button.disabled=true;
    button.setAttribute('aria-busy','true');
    if(url==='/api/export')$('#exportSummary').textContent='Generando el documento de Word…';
    try {
        if(dirty&&!await save(true))throw new Error('Guarda los cambios antes de exportar.');
        const response=await api(url,{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({job_id:job,data,template_id})});
        saveBlob(await response.blob(),name);
        $('#exportDialog').close();
        toast(url==='/api/export'?'Word generado':'JSON descargado');
    }catch(error){
        $('#exportSummary').textContent=error.message;
        toast(error.message,'warn');
    }finally{exporting=false;button.disabled=false;button.removeAttribute('aria-busy')}
}
function restoreUndoState(state){
    const revision=data.workspace_revision, audit=data.audit_log;
    data=JSON.parse(state);data.workspace_revision=revision;data.audit_log=audit;
    markDirty();renderAll();renderOverlay();
}
function undo(){if(!undoStack.length)return toast('No hay cambios para deshacer','warn');redoStack.push(JSON.stringify(data));restoreUndoState(undoStack.pop())}
function redo(){if(!redoStack.length)return toast('No hay cambios para rehacer','warn');undoStack.push(JSON.stringify(data));restoreUndoState(redoStack.pop())}
function autosave(){if(dirty&&!saveFlight&&!conflicted)return save(true)}
setInterval(autosave,20000);
$('#newPdfBtn').onclick=async()=>{if(!dirty||await save())location.href='/'};
$('#shutdownBtn').onclick=async()=>{
    if(dirty&&!await save())return;
    if(!confirm('¿Apagar el servidor local de FiscalOps?'))return;
    try{await api('/api/shutdown',{method:'POST'});document.body.innerHTML='<main class="shutdown-screen"><h1>Servidor apagado</h1><p>Puede cerrar esta pestaña.</p></main>'}
    catch(error){toast(error.message,'warn')}
};
const manualOcr=setupManualOcr();
init();
