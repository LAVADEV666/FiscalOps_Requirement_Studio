'use strict';
const homePreferenceKey='fiscalops.home.preferences.v2';
const readPreferences=()=>{try{const value=JSON.parse(localStorage.getItem(homePreferenceKey));return value&&typeof value==='object'&&!Array.isArray(value)?value:{}}catch{return {}}};
const homePrefs=readPreferences();
let sessionsCache=[],companiesCache=[],backupsCache=[],recordView=homePrefs.view==='companies'?'companies':'sessions';
let casePage=0,backupPage=0,casePageSize=5,backupPageSize=5,cleanupCandidates=[];
function homeMessage(text, undo) {
    const node=$('#homeToast'); node.replaceChildren();
    const label=document.createElement('span'); label.textContent=text; node.append(label);
    if (undo) {
        const button=document.createElement('button'); button.type='button'; button.textContent='Deshacer';
        button.onclick=async()=>{button.disabled=true;clearTimeout(node.timer);label.textContent='Recuperando sesiones…';try{await undo();node.hidden=true}catch(error){homeMessage(error.message)}};
        node.append(button);
    }
    node.hidden=false;clearTimeout(node.timer);node.timer=setTimeout(()=>node.hidden=true,undo?10000:4500);
}
async function undoRetirement(items) {
    const failures=[];
    for (let index=0;index<items.length;index+=4) {
        const results=await Promise.allSettled(items.slice(index,index+4).map(item=>jsonRequest('/api/maintenance/retired/'+item.trash_id+'/restore',{method:'POST'})));
        failures.push(...results.filter(result=>result.status==='rejected'));
    }
    await Promise.all([loadCases(),loadRetired()]);
    if(failures.length)throw new Error((items.length-failures.length)+' sesiones recuperadas; '+failures.length+' requieren revisión en la papelera.');
}
async function retireSession(id, button) {
    const item=sessionsCache.find(item=>item.job_id===id);if(!item)return;
    button.disabled=true;button.closest('.record-row')?.classList.add('is-retiring');
    try {
        const retired=await jsonRequest('/api/sessions/'+id+'/retire',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_updated_at:item.updated_at||null})});
        await Promise.all([loadCases(),loadRetired()]);
        homeMessage('Sesión retirada. Puedes recuperarla de la papelera.',()=>undoRetirement([retired]));
    } catch(error) { button.disabled=false;button.closest('.record-row')?.classList.remove('is-retiring');homeMessage(error.message); }
}

function storePreferences(){Object.assign(homePrefs,{view:recordView,caseSearch:$('#caseSearch').value,caseSort:$('#caseSort').value,caseFilter:$('#caseFilter').value,backupSearch:$('#backupSearch').value,backupSort:$('#backupSort').value,backupFilter:$('#backupFilter').value,density:$('#density').value});try{localStorage.setItem(homePreferenceKey,JSON.stringify(homePrefs))}catch{}}
async function homeRequest(url,options={}){const response=await fetch(url,{cache:'no-store',...options});if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{}throw new Error(typeof detail==='string'?detail:detail?.message||'No se pudo completar la operación.')}return response}
const jsonRequest=async(url,options)=> (await homeRequest(url,options)).json();
const putJSON=(url,payload)=>jsonRequest(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
const dateLabel=value=>value?new Date(value).toLocaleDateString('es-MX',{year:'numeric',month:'short',day:'numeric'}):'Sin fecha';
const normalizeSearch=value=>String(value||'').normalize('NFD').replace(/\p{Diacritic}/gu,'').toLocaleLowerCase('es-MX');
const matchesSearch=(value,query)=>normalizeSearch(value).includes(normalizeSearch(query.trim()));
const colorValue=value=>/^#[0-9a-f]{6}$/i.test(value||'')?value:'#63418b';
function emptyRecords(message){return '<p class="registry-empty">'+desktopIcon('folder')+escapeHTML(message)+'</p>'}
function activateHome(name,remember=true){
 const target=$('#home-'+name);if(!target)return;
 document.querySelectorAll('[data-home-tab]').forEach(button=>{const active=button.dataset.homeTab===name;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1});
 document.querySelectorAll('.home-panel').forEach(panel=>panel.hidden=panel!==target);
 if(remember){homePrefs.tab=name;try{localStorage.setItem(homePreferenceKey,JSON.stringify(homePrefs))}catch{}history.replaceState(null,'','#'+name)}
 if(name==='cases')renderCases();if(name==='backups')renderBackups();
}
const tabButtons=[...document.querySelectorAll('[data-home-tab]')];
tabButtons.forEach((button,index)=>{button.onclick=()=>activateHome(button.dataset.homeTab);button.onkeydown=event=>{let next;if(event.key==='ArrowRight')next=(index+1)%tabButtons.length;if(event.key==='ArrowLeft')next=(index-1+tabButtons.length)%tabButtons.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabButtons.length-1;if(next!==undefined){event.preventDefault();activateHome(tabButtons[next].dataset.homeTab);tabButtons[next].focus()}}});
document.querySelectorAll('[data-home-target]').forEach(button=>button.onclick=()=>activateHome(button.dataset.homeTarget));
function routeHash(){const route=location.hash.slice(1);const aliases={intake:'import',templateLibrary:'templates',recentSessions:'backups',companyPanel:'cases'};activateHome(aliases[route]||route||homePrefs.tab||'import',false)}
window.addEventListener('hashchange',routeHash);
for(const key of ['caseSearch','caseSort','caseFilter','backupSearch','backupSort','backupFilter','density'])if(homePrefs[key]!==undefined)$('#'+key).value=homePrefs[key];
if(!$('#density').value)$('#density').value='compact';
document.body.dataset.density=$('#density').value;
$('#density').onchange=()=>{document.body.dataset.density=$('#density').value;try{localStorage.setItem('fiscalops.density',$('#density').value)}catch{}storePreferences();resizeRecords()};
for(const id of ['caseSearch','caseSort','caseFilter'])$('#'+id).addEventListener(id==='caseSearch'?'input':'change',()=>{casePage=0;storePreferences();renderCases()});
for(const id of ['backupSearch','backupSort','backupFilter'])$('#'+id).addEventListener(id==='backupSearch'?'input':'change',()=>{backupPage=0;storePreferences();renderBackups()});
document.querySelectorAll('[data-record-view]').forEach(button=>button.onclick=()=>{recordView=button.dataset.recordView;casePage=0;storePreferences();resizeRecords();renderCases()});
async function loadCases(){
 const results=await Promise.allSettled([jsonRequest('/api/sessions'),jsonRequest('/api/companies')]);
 if(results[0].status==='fulfilled')sessionsCache=results[0].value.sessions||[];else homeMessage(results[0].reason.message);
 if(results[1].status==='fulfilled')companiesCache=results[1].value.companies||[];else homeMessage(results[1].reason.message);
 renderCases();
}
async function loadBackups(){try{backupsCache=(await jsonRequest('/api/backups')).backups||[];renderBackups()}catch(error){$('#backupList').innerHTML=emptyRecords(error.message)}}
document.querySelector('[data-refresh="cases"]').onclick=loadCases;document.querySelector('[data-refresh="backups"]').onclick=loadBackups;
function filteredSessions(){const filter=$('#caseFilter').value,query=$('#caseSearch').value;const items=sessionsCache.filter(item=>{const organization=item.organization||{};return (filter==='all'||(filter==='archived'?organization.archived:filter==='pinned'?organization.pinned&&!organization.archived:!organization.archived))&&matchesSearch([item.taxpayer_name,item.source_file,item.rfc,item.job_id,organization.group].join(' '),query)});return items.sort((a,b)=>Number(!!b.organization?.pinned)-Number(!!a.organization?.pinned)||sortRecords(a,b,$('#caseSort').value))}
function sortRecords(a,b,sort){return sort==='rfc'?String(a.rfc||'').localeCompare(b.rfc||''):sort==='name'?String(a.taxpayer_name||a.name||a.title||a.source_file||'').localeCompare(b.taxpayer_name||b.name||b.title||b.source_file||'','es'):String(b.updated_at||b.created_at||'').localeCompare(a.updated_at||a.created_at||'')}
function pageSlice(items,page,size){const pages=Math.max(1,Math.ceil(items.length/size));page=Math.min(page,pages-1);return {page,pages,items:items.slice(page*size,(page+1)*size)}}
function renderCases(){
 const companies=recordView==='companies';$('#sessionList').hidden=companies;$('#companyList').hidden=!companies;$('#caseFilter').hidden=companies;
 document.querySelectorAll('[data-record-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.recordView===recordView)));
 const items=companies?companiesCache.filter(item=>matchesSearch(item.name+' '+item.rfc,$('#caseSearch').value)).sort((a,b)=>sortRecords(a,b,$('#caseSort').value)):filteredSessions();
 const slice=pageSlice(items,casePage,casePageSize);casePage=slice.page;
 if(companies){$('#companyList').innerHTML=slice.items.map(item=>`<article class="company-card"><div class="company-cover" style="--company-color:${colorValue(item.color)}">${item.cover_version&&item.use_cover!==false?`<img loading="lazy" src="/api/companies/${encodeURIComponent(item.rfc)}/cover?v=${encodeURIComponent(item.cover_version)}" alt="Portada de ${escapeHTML(item.name)}">`:escapeHTML(item.emoji||'🏢')}</div><div class="company-card-body"><h2 title="${escapeHTML(item.name)}">${escapeHTML(item.name)}</h2><small>${escapeHTML(item.rfc)} · ${Number(item.case_count)||0} expedientes</small><div class="record-actions"><button data-company-open="${escapeHTML(item.rfc)}">Ver expedientes</button><button data-company-appearance="${escapeHTML(item.rfc)}" aria-label="Personalizar ${escapeHTML(item.name)}">Personalizar</button></div></div></article>`).join('')||emptyRecords('No hay empresas que coincidan con la búsqueda.');
 $('#companyList').querySelectorAll('[data-company-open]').forEach(button=>button.onclick=()=>openCompany(button.dataset.companyOpen));
 $('#companyList').querySelectorAll('[data-company-appearance]').forEach(button=>button.onclick=()=>openAppearance(button.dataset.companyAppearance));
 }else{$('#sessionList').innerHTML=slice.items.map(item=>`<article class="record-row"><div class="record-name"><strong title="${escapeHTML(item.taxpayer_name||item.source_file||item.job_id)}">${item.organization?.pinned?'★ ':''}${escapeHTML(item.taxpayer_name||item.source_file||'Expediente '+item.job_id.slice(0,8))}</strong><small>${escapeHTML(item.rfc||'RFC pendiente')} · ${Number(item.points)||0} numerales · ${dateLabel(item.updated_at)}${item.organization?.group?' · '+escapeHTML(item.organization.group):''}</small></div><div class="record-actions">${item.recoverable?`<a href="/audit?job=${encodeURIComponent(item.job_id)}">Abrir</a>`:'<span>Revisar registro</span>'}<button class="more-record" data-session-menu="${escapeHTML(item.job_id)}" aria-label="Acciones del expediente ${escapeHTML(item.taxpayer_name||item.job_id)}">···</button><button class="session-remove" data-retire-session="${escapeHTML(item.job_id)}" title="Retirar sesión · recuperable en la papelera" aria-label="Retirar sesión ${escapeHTML(item.taxpayer_name||item.source_file||item.job_id)}">×</button></div></article>`).join('')||emptyRecords('No hay expedientes que coincidan con los filtros.');$('#sessionList').querySelectorAll('[data-session-menu]').forEach(button=>button.onclick=()=>sessionActions(button.dataset.sessionMenu));$('#sessionList').querySelectorAll('[data-retire-session]').forEach(button=>button.onclick=()=>retireSession(button.dataset.retireSession,button))}
 $('#caseCount').textContent=items.length+' '+(companies?'empresas':'expedientes');$('#casePage').textContent=(casePage+1)+' / '+slice.pages;$('#casePrev').disabled=casePage===0;$('#caseNext').disabled=casePage+1===slice.pages;
}
$('#casePrev').onclick=()=>{casePage--;renderCases()};$('#caseNext').onclick=()=>{casePage++;renderCases()};
function renderBackups(){const filter=$('#backupFilter').value;const items=backupsCache.filter(item=>(filter==='all'||(filter==='archived'?item.archived:!item.archived))&&matchesSearch(item.title+' '+item.rfc,$('#backupSearch').value)).sort((a,b)=>sortRecords(a,b,$('#backupSort').value));const slice=pageSlice(items,backupPage,backupPageSize);backupPage=slice.page;$('#backupList').innerHTML=slice.items.map(item=>`<article class="record-row"><div class="record-name"><strong title="${escapeHTML(item.title)}">${escapeHTML(item.title)}</strong><small>${escapeHTML(item.rfc||'RFC pendiente')} · ${dateLabel(item.created_at)} · ${(Number(item.bytes)/1024/1024).toFixed(2)} MB${item.available?'':' · Archivo no disponible'}</small></div><div class="record-actions"><button data-backup-restore="${item.id}" ${item.available?'':'disabled'}>Restaurar</button><button class="more-record" data-backup-menu="${item.id}" aria-label="Acciones del resguardo ${escapeHTML(item.title)}">···</button></div></article>`).join('')||emptyRecords('No hay resguardos que coincidan con los filtros.');$('#backupList').querySelectorAll('[data-backup-restore]').forEach(button=>button.onclick=()=>restoreManagedBackup(button.dataset.backupRestore,button));$('#backupList').querySelectorAll('[data-backup-menu]').forEach(button=>button.onclick=()=>backupActions(button.dataset.backupMenu));$('#backupCount').textContent=items.length+' resguardos';$('#backupPage').textContent=(backupPage+1)+' / '+slice.pages;$('#backupPrev').disabled=backupPage===0;$('#backupNext').disabled=backupPage+1===slice.pages}
$('#backupPrev').onclick=()=>{backupPage--;renderBackups()};$('#backupNext').onclick=()=>{backupPage++;renderBackups()};
function resizeRecords(){const list=recordView==='companies'?$('#companyList'):$('#sessionList');if(list.clientHeight){const companyColumns=recordView==='companies'?getComputedStyle(list).gridTemplateColumns.split(' ').length:1;casePageSize=recordView==='companies'?Math.max(1,Math.floor(list.clientHeight/199))*companyColumns:Math.max(1,Math.floor(list.clientHeight/(document.body.dataset.density==='comfortable'?98:innerHeight<=650?77:84)));renderCases()}if($('#backupList').clientHeight){backupPageSize=Math.max(1,Math.floor($('#backupList').clientHeight/(innerHeight<=650?77:84)));renderBackups()}}
new ResizeObserver(resizeRecords).observe($('.shell-main'));new ResizeObserver(resizeRecords).observe($('#sessionList'));new ResizeObserver(resizeRecords).observe($('#companyList'));new ResizeObserver(resizeRecords).observe($('#backupList'));
function actionDialog(title,content){const dialog=document.createElement('dialog');dialog.className='premium-dialog';dialog.innerHTML='<header><h2></h2><button data-dialog-close aria-label="Cerrar">×</button></header>'+content;dialog.querySelector('h2').textContent=title;document.body.append(dialog);dialog.querySelector('[data-dialog-close]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.showModal();return dialog}
function sessionActions(id){const item=sessionsCache.find(item=>item.job_id===id),organization=item.organization||{};const dialog=actionDialog('Organizar expediente',`<p>${escapeHTML(item.taxpayer_name||item.source_file||id)}</p><form><label>Grupo o etiqueta<input name="group" maxlength="60" value="${escapeHTML(organization.group||'')}" placeholder="Ej. Requerimientos 2026"></label><label><span><input type="checkbox" name="pinned" ${organization.pinned?'checked':''}> Favorito</span></label><label><span><input type="checkbox" name="archived" ${organization.archived?'checked':''}> Archivado</span></label><p role="status"></p><footer><button type="button" data-resguardo ${item.recoverable?'':'disabled'}>Crear resguardo local</button><button class="primary">Guardar organización</button></footer></form>`);const form=dialog.querySelector('form'),message=dialog.querySelector('[role=status]');form.onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await putJSON('/api/sessions/'+id+'/organization',{group:form.elements.group.value,pinned:form.elements.pinned.checked,archived:form.elements.archived.checked});await loadCases();dialog.close();homeMessage('Organización guardada.')}catch(error){message.textContent=error.message}finally{button.disabled=false}};dialog.querySelector('[data-resguardo]').onclick=async event=>{const button=event.currentTarget;button.disabled=true;message.textContent='Creando y verificando resguardo…';try{await jsonRequest('/api/backups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:id})});await loadBackups();message.textContent='Resguardo creado. Disponible en la pestaña Resguardos.';homeMessage('Resguardo local creado.')}catch(error){message.textContent=error.message}finally{button.disabled=false}}}
function backupActions(id){const item=backupsCache.find(item=>item.id===id);const dialog=actionDialog('Organizar resguardo',`<form><label>Nombre<input name="title" maxlength="160" required value="${escapeHTML(item.title)}"></label><label><span><input type="checkbox" name="archived" ${item.archived?'checked':''}> Archivado</span></label><p>SHA-256: <small style="overflow-wrap:anywhere">${escapeHTML(item.sha256)}</small></p><p role="status"></p><footer><a class="session-link" href="/api/backups/${id}/file" download>Descargar ZIP</a><button class="primary">Guardar</button></footer></form>`);const form=dialog.querySelector('form');form.onsubmit=async event=>{event.preventDefault();event.submitter.disabled=true;try{await putJSON('/api/backups/'+id,{title:form.elements.title.value,archived:form.elements.archived.checked});await loadBackups();dialog.close();homeMessage('Resguardo actualizado.')}catch(error){dialog.querySelector('[role=status]').textContent=error.message;event.submitter.disabled=false}}}
async function openCompany(rfc){const item=companiesCache.find(item=>item.rfc===rfc);const dialog=actionDialog(item.name,'<p role="status">Consultando expedientes…</p><div data-cases></div>');try{const {cases}=await jsonRequest('/api/companies/'+encodeURIComponent(rfc)+'/cases');if(!dialog.isConnected)return;const list=dialog.querySelector('[data-cases]');const sessions=sessionsCache.filter(item=>item.rfc===rfc&&item.recoverable);list.innerHTML=cases.map(item=>`<div class="record-row"><div class="record-name"><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.case_id)}</small></div><button data-open-case="${escapeHTML(item.case_id)}">Abrir</button></div>`).join('')+sessions.map(item=>`<div class="record-row"><div class="record-name"><strong>${escapeHTML(item.source_file||'Sesión de trabajo')}</strong><small>${dateLabel(item.updated_at)}</small></div><a href="/audit?job=${item.job_id}">Abrir sesión</a></div>`).join('');dialog.querySelector('[role=status]').textContent=cases.length||sessions.length?'Selecciona un expediente o sesión.':'Esta empresa aún no tiene expedientes. Importa un PDF con su RFC.';list.querySelectorAll('[data-open-case]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const result=await jsonRequest('/api/cases/'+encodeURIComponent(rfc)+'/'+encodeURIComponent(button.dataset.openCase)+'/open',{method:'POST'});location.assign('/audit?job='+result.job_id)}catch(error){dialog.querySelector('[role=status]').textContent=error.message;button.disabled=false}})}catch(error){dialog.querySelector('[role=status]').textContent=error.message}}
let appearanceCompany;
function paintAppearance(){const preview=$('#appearancePreview');preview.style.backgroundColor=$('#companyColor').value;const file=$('#companyCover').files[0];preview.replaceChildren();if(file){const image=document.createElement('img');const url=URL.createObjectURL(file);image.onload=()=>URL.revokeObjectURL(url);image.src=url;image.alt='Vista previa de portada';preview.append(image)}else if(appearanceCompany.cover_version&&$('#companyUseCover').checked){const image=document.createElement('img');image.src='/api/companies/'+encodeURIComponent(appearanceCompany.rfc)+'/cover?v='+appearanceCompany.cover_version;image.alt='Portada guardada';preview.append(image)}else preview.textContent=$('#companyEmoji').value}
function openAppearance(rfc){appearanceCompany=companiesCache.find(item=>item.rfc===rfc);$('#companyEmoji').value=appearanceCompany.emoji||'🏢';$('#companyColor').value=colorValue(appearanceCompany.color);$('#companyCover').value='';$('#companyUseCover').checked=appearanceCompany.use_cover!==false;$('#appearanceDialog [role=status]').textContent='';paintAppearance();$('#appearanceDialog').showModal()}
$('#appearanceForm').oninput=paintAppearance;
$('#appearanceForm').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;const message=$('#appearanceDialog [role=status]');try{const rfc=encodeURIComponent(appearanceCompany.rfc),file=$('#companyCover').files[0];if(file){if(file.size>4*1024*1024||!file.name.toLowerCase().endsWith('.png'))throw new Error('Selecciona un PNG de hasta 4 MB.');const form=new FormData();form.set('file',file);await jsonRequest('/api/companies/'+rfc+'/cover',{method:'PUT',body:form})}await putJSON('/api/companies/'+rfc+'/appearance',{emoji:$('#companyEmoji').value,color:$('#companyColor').value,use_cover:$('#companyUseCover').checked});await loadCases();window.dispatchEvent(new CustomEvent('company:appearance-changed',{detail:{rfc:appearanceCompany.rfc}}));$('#appearanceDialog').close();homeMessage('Apariencia de empresa guardada.')}catch(error){message.textContent=error.message}finally{button.disabled=false}};
$('#newCompany').onclick=()=>{$('#companyForm').reset();$('#companyDialog [role=status]').textContent='';$('#companyDialog').showModal()};
$('#companyForm').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await jsonRequest('/api/companies',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rfc:$('#companyRfc').value,name:$('#companyName').value})});await loadCases();recordView='companies';casePage=0;renderCases();storePreferences();$('#companyDialog').close();homeMessage('Empresa guardada.')}catch(error){$('#companyDialog [role=status]').textContent=error.message}finally{button.disabled=false}};
document.querySelectorAll('dialog [data-dialog-close]').forEach(button=>button.onclick=()=>button.closest('dialog').close());
async function restoreBlob(file){const form=new FormData();form.append('file',file,'FiscalOps_Resguardo.zip');const result=await jsonRequest('/api/workspace/restore',{method:'POST',body:form});location.assign('/audit?job='+encodeURIComponent(result.job_id))}
async function restoreManagedBackup(id,button){if(!confirm('¿Restaurar este resguardo en una sesión nueva? El expediente original se conservará.'))return;button.disabled=true;try{await restoreBlob(await(await homeRequest('/api/backups/'+id+'/file')).blob())}catch(error){homeMessage(error.message);button.disabled=false}}
$('#restoreBackup').onclick=()=>$('#backupFile').click();$('#backupFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;const button=$('#restoreBackup'),message=$('#backupStatus');button.disabled=true;message.hidden=false;message.textContent='Verificando resguardo…';try{await restoreBlob(file)}catch(error){message.textContent=error.message}finally{button.disabled=false;event.target.value=''}};
$('#diagnosticBtn').onclick=async event=>{event.currentTarget.disabled=true;try{$('#diagnosticResult').textContent=JSON.stringify(await jsonRequest('/api/diagnostic'),null,2)}catch(error){$('#diagnosticResult').textContent=error.message}finally{$('#diagnosticBtn').disabled=false}};
function clearCleanup(){cleanupCandidates=[];$('#cleanupList').replaceChildren();$('#cleanupApply').disabled=true;$('#cleanupAll').disabled=true;$('#cleanupAll').textContent='Seleccionar todas'}
$('#retentionDays').oninput=clearCleanup;
$('#cleanupPreview').onclick=async event=>{const button=event.currentTarget;button.disabled=true;clearCleanup();try{const result=await jsonRequest('/api/maintenance/cleanup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days:Number($('#retentionDays').value),dry_run:true})});cleanupCandidates=result.items;$('#cleanupAll').disabled=!result.count;$('#cleanupList').innerHTML=result.items.map(item=>{const session=sessionsCache.find(session=>session.job_id===item.job_id);return `<label><input type="checkbox" value="${item.job_id}"><span>${escapeHTML(session?.taxpayer_name||session?.source_file||item.job_id.slice(0,8))}<small> · ${dateLabel(item.modified)}</small></span></label>`}).join('');$('#maintenanceResult').textContent=result.count?result.count+' registros encontrados. Selecciona únicamente los que quieras retirar.':'No hay registros anteriores a esa fecha.';$('#cleanupList').onchange=()=>$('#cleanupApply').disabled=!$('#cleanupList input:checked')}catch(error){$('#maintenanceResult').textContent=error.message}finally{button.disabled=false}};
$('#cleanupAll').onclick=()=>{
    const inputs=[...document.querySelectorAll('#cleanupList input')];
    const checked=inputs.some(input=>!input.checked);
    inputs.forEach(input=>input.checked=checked);$('#cleanupApply').disabled=!checked;
    $('#cleanupAll').textContent=checked?'Quitar selección':'Seleccionar todas';
};
$('#cleanupApply').onclick=async()=>{
    const ids=[...document.querySelectorAll('#cleanupList input:checked')].map(input=>input.value);
    const selected=cleanupCandidates.filter(item=>ids.includes(item.job_id));if(!selected.length)return;
    const button=$('#cleanupApply');button.disabled=true;
    try {
        const result=await jsonRequest('/api/maintenance/cleanup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({days:Number($('#retentionDays').value),dry_run:false,selected:Object.fromEntries(selected.map(item=>[item.job_id,item.modified]))})});
        clearCleanup();$('#maintenanceResult').textContent=result.count+' sesiones retiradas. Las modificadas durante la revisión se conservaron.';
        await Promise.all([loadCases(),loadRetired()]);
        homeMessage(result.count+' sesiones retiradas.',result.items.length?()=>undoRetirement(result.items):null);
    } catch(error) { homeMessage(error.message);button.disabled=false; }
};
async function loadRetired() {
    try {
        const {items} = await jsonRequest('/api/maintenance/retired');
        $('#retiredList').innerHTML = items.map(item => `<div class="record-row"><div class="record-name"><strong title="${escapeHTML(item.job_id)}">${escapeHTML(item.label || 'Expediente ' + item.job_id.slice(0,8))}</strong><small>${escapeHTML(item.rfc || item.job_id.slice(0,8))} · ${dateLabel(item.removed_at)}</small></div><div class="record-actions"><button data-undo-retire="${item.trash_id}">Recuperar</button><button class="danger-button" data-purge-retired="${item.trash_id}" aria-label="Eliminar definitivamente ${escapeHTML(item.label || item.job_id)}">Eliminar…</button></div></div>`).join('') || '<p>La papelera está vacía.</p>';
        $('#retiredList').querySelectorAll('[data-undo-retire]').forEach(button => button.onclick = async () => {
            button.disabled = true;
            try {
                await jsonRequest('/api/maintenance/retired/' + button.dataset.undoRetire + '/restore', {method:'POST'});
                await Promise.all([loadCases(), loadRetired()]);
                homeMessage('Expediente recuperado.');
            } catch (error) { homeMessage(error.message); button.disabled = false; }
        });
        $('#retiredList').querySelectorAll('[data-purge-retired]').forEach(button => button.onclick = () => {
            const item = items.find(item => item.trash_id === button.dataset.purgeRetired);
            const dialog = actionDialog('Eliminar definitivamente', `<form><p>Se eliminará el expediente retirado <strong>${escapeHTML(item.label || item.job_id)}</strong> (${escapeHTML(item.job_id)}). Esta acción libera su espacio y no se puede deshacer. Los resguardos independientes se conservan.</p><p role="status"></p><footer><button type="button" data-cancel>Cancelar</button><button class="danger-button" data-permanent-delete>Eliminar definitivamente</button></footer></form>`);
            const form = dialog.querySelector('form'), submit = dialog.querySelector('[data-permanent-delete]');
            dialog.querySelector('[data-cancel]').onclick = () => dialog.close();
            form.onsubmit = async event => {
                event.preventDefault();
                submit.disabled = true;
                try {
                    await jsonRequest('/api/maintenance/retired/' + item.trash_id + '/purge', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_id:item.job_id, confirmed:true})});
                    await loadRetired(); dialog.close(); homeMessage('Registro eliminado de la papelera.');
                } catch (error) { dialog.querySelector('[role=status]').textContent = error.message; submit.disabled = false; }
            };
        });
    } catch (error) { $('#retiredList').textContent = error.message; }
}
const effects=window.FiscalMotion.getPreferences();
$('#animationsEnabled').checked=effects.enabled;$('#mouseTrailEnabled').checked=effects.trail;
$('#animationsEnabled').onchange=()=>window.FiscalMotion.setPreferences({enabled:$('#animationsEnabled').checked});
$('#mouseTrailEnabled').onchange=()=>window.FiscalMotion.setPreferences({trail:$('#mouseTrailEnabled').checked});
routeHash();loadCases();loadBackups();loadRetired();
