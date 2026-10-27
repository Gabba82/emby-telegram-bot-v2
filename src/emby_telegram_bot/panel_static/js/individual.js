/* Flujo 1×1 separado del envío masivo. El servidor conserva la autoridad sobre
 * estados, decisiones, idempotencia y resultados; esta vista solo los presenta. */
(function (root) {
  'use strict';

  var Api=root.EmbyApi,V=root.EmbyViews,H=V.h,esc=V.esc;
  var LABEL={sent:'Enviado',failed:'Fallido',pending:'Pendiente',uncertain:'Incierto',history_unknown:'Desconocido',skipped:'Omitido',completed:'Completada',interrupted:'Interrumpida'};

  function fresh(){return {query:'',catalog:{status:'idle',items:[],error:null},itemId:'',chatId:'',decision:null,plan:null,result:null,ack:false,busy:false,error:'',unknown:false};}

  function attach(store){
    var timer=null,seq=0;
    store.state.individual=fresh();
    function I(){return store.state.individual;}
    function emit(){store.emit();}
    function load(){
      var me=++seq,i=I();i.catalog.status='loading';i.catalog.error=null;emit();
      return Api.individualCatalog({query:i.query.trim(),page:1}).then(function(d){
        if(me!==seq)return;I().catalog={status:'ok',items:d.items,error:null};
        if(I().itemId&&!d.items.some(function(x){return x.id===I().itemId;}))I().itemId='';emit();
      },function(err){if(me!==seq||store.lostSession(err))return;I().catalog={status:'error',items:[],error:err};emit();});
    }
    function invalidate(){var i=I();i.plan=null;i.result=null;i.decision=null;i.ack=false;i.error='';i.unknown=false;}
    function search(value){I().query=value;invalidate();clearTimeout(timer);timer=setTimeout(load,300);emit();}
    function selectItem(value){I().itemId=value;invalidate();emit();}
    function selectChat(value){I().chatId=value;invalidate();emit();}
    function prepare(){
      var i=I();if(i.busy||!i.itemId||!i.chatId)return Promise.resolve();
      i.busy=true;i.error='';i.unknown=false;i.result=null;emit();
      var payload={item_id:i.itemId,chat_id:i.chatId};if(i.decision)payload.decision=i.decision;
      return Api.individualPrepare(payload).then(function(plan){i.busy=false;i.plan=plan;i.ack=false;emit();},function(err){
        i.busy=false;if(store.lostSession(err))return;i.error=Api.describe(err);emit();
      });
    }
    function decide(value){var i=I();i.decision=value;i.plan=null;i.ack=false;prepare();}
    function setAck(on){I().ack=!!on;I().error='';emit();}
    function check(){
      var i=I();if(!i.plan||i.busy)return Promise.resolve();i.busy=true;i.error='';emit();
      return Api.batch(i.plan.batch_id).then(function(result){i.busy=false;i.result=result;i.unknown=false;emit();},function(err){i.busy=false;if(store.lostSession(err))return;i.error=Api.describe(err);emit();});
    }
    function confirm(){
      var i=I(),row=i.plan&&i.plan.rows[0];
      if(i.busy||i.result||!i.ack||!i.plan||!i.plan.can_confirm||!store.state.session.sends)return Promise.resolve();
      i.busy=true;i.error='';i.unknown=false;emit();
      return Api.confirm(i.plan.batch_id,!!row.duplicate_risk).then(function(result){i.busy=false;i.result=result;emit();},function(err){
        i.busy=false;if(store.lostSession(err))return;
        i.unknown=Api.isUncertain(err)||err.code==='in_progress';i.error=Api.describe(err)+(i.unknown?' No repitas la operación: consulta el resultado guardado.':'');emit();
      });
    }
    function reset(){store.state.individual=fresh();load();emit();}
    function enter(){if(I().catalog.status==='idle')load();}
    store.registerView('individual',enter);store.onReset(function(){clearTimeout(timer);seq++;store.state.individual=fresh();});
    store.individual={search:search,selectItem:selectItem,selectChat:selectChat,prepare:prepare,decide:decide,setAck:setAck,confirm:confirm,check:check,reset:reset};
  }

  function options(items,selected,placeholder,label){
    return '<option value="">'+esc(placeholder)+'</option>'+items.map(function(x){var id=x.id||x.Id;return '<option value="'+esc(id)+'"'+(id===selected?' selected':'')+'>'+esc(label(x))+'</option>';}).join('');
  }
  function badge(state){return H.statusBadge(state==='history_unknown'?'history_unknown':state,LABEL[state]||state);}
  function current(plan){
    var c=plan.current||{},a=c.last_attempt;
    return '<section class="panel"><h3>Estado actual</h3><div class="toolbar">'+badge(c.state)+'<span class="muted">'+esc(c.result||'Sin resultado conocido.')+'</span></div>'+
      '<dl class="rdetail"><div><dt>Última actualización</dt><dd>'+esc(c.updated_at?H.fmtDateTime(c.updated_at):'Sin fecha conocida')+'</dd></div><div><dt>Último intento</dt><dd>'+esc(a?(LABEL[a.status]||a.status)+' · '+H.fmtDateTime(a.finished_at||a.created_at):'No consta')+'</dd></div><div><dt>Resultado</dt><dd>'+esc(c.message_id?'Mensaje '+c.message_id:(c.error_type||'Sin dato adicional'))+'</dd></div></dl></section>';
  }
  function preview(row){return '<section class="panel"><h3>Vista previa exacta</h3><p class="muted">'+esc(row.title)+' → '+esc(row.chat_label)+' <span class="mono">'+esc(row.chat_id)+'</span></p><div class="tg"><div class="tg__bubble"><div class="tg__text">'+esc(row.preview).replace(/\n/g,'<br>')+'</div></div></div></section>';}
  function planView(store){
    var i=store.state.individual,p=i.plan,row=p&&p.rows[0];if(!p||!row)return '';
    var decision='';
    if(row.action==='decision')decision='<div class="alert alert--warn"><b>Decisión explícita necesaria</b><p>El panel no puede demostrar que Telegram no lo recibió. Enviar podría crear un duplicado.</p><div class="btn-row"><button class="btn" type="button" data-action="individual-decision" data-value="skip">No enviar</button><button class="btn btn--danger" type="button" data-action="individual-decision" data-value="send">Asumir el riesgo y preparar</button></div></div>';
    else if(row.action==='skip')decision='<div class="alert alert--ok"><b>No se enviará</b><p>Ya existe una entrega confirmada o elegiste omitirla. La protección automática impide el reenvío.</p></div>';
    var send=p.can_confirm?'<div class="alert '+(row.duplicate_risk?'alert--warn':'')+'"><label class="checkline"><input type="checkbox" data-action="individual-ack"'+(i.ack?' checked':'')+'> Confirmo este único contenido y este único destino'+(row.duplicate_risk?', y acepto el riesgo de duplicación':'')+'.</label><button type="button" class="btn btn--primary" data-action="individual-confirm"'+(!i.ack||!store.state.session.sends||i.busy?' disabled':'')+'>'+(i.busy?'Procesando…':'Confirmar recuperación')+'</button>'+(store.state.session.sends?'':'<p class="muted">Los envíos están bloqueados por PANEL_ALLOW_SENDS=false.</p>')+'</div>':'';
    return current(p)+preview(row)+decision+send;
  }
  function resultView(i){
    if(!i.result)return '';
    var rows=i.result.results||[],r=rows[0];
    return '<section class="panel"><h3>Resultado consultable</h3><div class="alert '+(r&&r.status==='sent'?'alert--ok':'alert--warn')+'"><b>'+esc(LABEL[i.result.status]||i.result.status)+'</b><p>'+(r?badge(r.status)+' '+esc(r.error_type|| (r.message_id?'Mensaje '+r.message_id:'Sin identificador de mensaje')):'No hay resultado de entrega guardado.')+'</p></div><div class="btn-row"><button type="button" class="btn" data-action="individual-check">Actualizar resultado</button><button type="button" class="btn" data-action="individual-reset">Nueva recuperación individual</button></div></section>';
  }
  function view(store){
    var i=store.state.individual,chats=store.state.chats.list||[];
    var itemOpts=options(i.catalog.items,i.itemId,i.catalog.status==='loading'?'Buscando…':'Selecciona un contenido',function(x){return x.title+(x.year?' · '+x.year:'');});
    var chatOpts=options(chats,i.chatId,'Selecciona un destino',function(x){return store.chatOptionLabel(x.id);});
    var err=i.error?'<div class="alert alert--err" role="alert">'+esc(i.error)+(i.unknown&&i.plan?' <button type="button" class="btn btn--sm" data-action="individual-check">Consultar resultado</button>':'')+'</div>':'';
    var empty=i.catalog.status==='ok'&&!i.catalog.items.length?'<p class="empty">No se encontraron películas, series o episodios con esa búsqueda.</p>':'';
    return '<header class="page-head"><h2>Recuperación individual</h2><p>Un contenido y un destino por operación. Este flujo no modifica ni reutiliza la recuperación masiva.</p></header>'+
      '<form id="individual-form" class="panel rform"><h3>1. Selección</h3><label class="field"><span>Buscar contenido</span><input type="search" data-action="individual-q" data-fid="individual-q" value="'+esc(i.query)+'" placeholder="Título"></label>'+empty+
      '<label class="field"><span>Película o episodio</span><select data-action="individual-item">'+itemOpts+'</select></label><label class="field"><span>Destino de Telegram</span><select data-action="individual-chat">'+chatOpts+'</select></label><p class="muted">El nombre es solo presentación; el envío conserva siempre el ID real.</p><button class="btn btn--primary" type="submit" data-action="individual-prepare"'+(!i.itemId||!i.chatId||i.busy?' disabled':'')+'>'+(i.busy?'Consultando…':'Preparar vista previa')+'</button></form>'+err+(i.result?'':planView(store))+resultView(i);
  }

  root.EmbyIndividual={attach:attach,view:view};
})(self);
