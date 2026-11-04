'use strict';
// Run the actual page hook inside a deterministic DOM/extension test harness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.join(__dirname, '..', 'extension', 'chromium');
const flush = async () => { for (let i=0; i<12; i++) await new Promise(r=>setImmediate(r)); };
async function until(predicate) { const deadline=Date.now()+4000; while(!predicate()){if(Date.now()>deadline)throw new Error('Async browser harness timeout');await new Promise(r=>setTimeout(r,2));} await flush(); }
function pageHarness(host='example.test', enabled=true, rejectChunks=false) {
  const listeners = new Map(), posts=[], clicks=[], created=new Map(), revoked=[], chunks=[];
  let number=0;
  class Anchor {
    constructor(){this.attrs={};this.style={};this.__idmBypassBlob=false;}
    set href(v){this.attrs.href=v;} get href(){return this.attrs.href||'';}
    set download(v){this.attrs.download=v;} get download(){return this.attrs.download||'';}
    getAttribute(k){return Object.hasOwn(this.attrs,k)?this.attrs[k]:null;}
    setAttribute(k,v){this.attrs[k]=v;} appendChild(){} remove(){} closest(){return this;}
    click(){clicks.push({url:this.href, filename:this.download, blob:created.get(this.href)});}
  }
  class Location {
    get href(){return this._href;} set href(v){this._href=v;}
    assign(v){this._href=v;} replace(v){this._href=v;}
  }
  const location=new Location();location.href=`https://${host}/watch?v=abc`;location.host=location.hostname=host;location.origin=`https://${host}`;
  class TestURL extends URL {
    static createObjectURL(blob){const u=`blob:test-${++number}`;created.set(u,blob);return u;}
    static revokeObjectURL(u){revoked.push(u);created.delete(u);}
  }
  class Reader {readAsDataURL(blob){blob.arrayBuffer().then(b=>{this.result=`data:application/octet-stream;base64,${Buffer.from(b).toString('base64')}`;this.onload();}).catch(e=>{this.error=e;this.onerror();});}}
  const dataset={idmLinuxCaptureEnabled:enabled?'1':'0',idmLinuxBlobReady:enabled?'1':'0'};
  const element={dataset,innerHTML:'',appendChild(){},querySelectorAll(){return[];}};
  const doc={documentElement:element,body:element,readyState:'complete',querySelectorAll(){return[];},querySelector(){return null;},getElementById(){return null;},createElement(n){return n==='a'?new Anchor():{...element,style:{},setAttribute(){},remove(){}};},addEventListener(){}};
  const add=(name,fn)=>{if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);};
  const fire=(name,data)=>{for(const fn of listeners.get(name)||[])fn(data);};
  const win={addEventListener:add,removeEventListener(){},open(u){return {native:true,url:u};},location,document:doc,
    postMessage(d){posts.push(d);if(d.__idmLinuxBlobRequest){if(win.onRpc)win.onRpc(d);let result={ok:true};if(d.action==='begin')result={ok:true,transferId:'test-id'};if(d.action==='chunk'){chunks.push(d);result={ok:!rejectChunks,received:d.offset+Buffer.from(d.dataBase64,'base64').length};}if(d.action==='finish')result={ok:true,takeover:true};setImmediate(()=>fire('message',{source:win,data:{...result,__idmLinuxBlobResult:true,reqId:d.reqId}}));}},
    fetch:async()=>({ok:true,headers:{get(){return'';}},clone(){return this;},text:async()=>'',json:async()=>({})})};
  function XHR(){}XHR.prototype.open=function(){};XHR.prototype.send=function(){};XHR.prototype.addEventListener=function(){};
  const timeout=(fn,ms)=>{const t=setTimeout(fn,ms);t.unref();return t;};
  const context=vm.createContext({window:win,document:doc,location,URL:TestURL,Location,HTMLAnchorElement:Anchor,Blob,FileReader:Reader,
    XMLHttpRequest:XHR,fetch:win.fetch,AbortController,TextDecoder,console,navigator:{userAgent:'test'},setTimeout:timeout,clearTimeout,setInterval(){return 1;},clearInterval(){},MutationObserver:class{observe(){} disconnect(){}},performance:{getEntriesByType(){return[];}},btoa:s=>Buffer.from(s,'binary').toString('base64'),atob:s=>Buffer.from(s,'base64').toString('binary')});
  return {win,doc,location,context,clicks,posts,created,revoked,chunks,Anchor,URL:TestURL,fire,load(){vm.runInContext(fs.readFileSync(path.join(root,'page_hook.js'),'utf8'),context);}};
}
function captionResponse(url, body, type='application/json') {
  return {ok:true,url,headers:{get(k){return k==='content-type'?type:k==='content-length'?String(Buffer.byteLength(body)):'';}},clone(){return this;},text:async()=>body};
}
async function externalCaptionTests(){
  for(const [host,body,expected] of [
    ['ok.ru',JSON.stringify({flashvars:{metadata:JSON.stringify({subtitles:[{lang:'tr',url:'../caption?id=7'}]})}}),'/caption?id=7'],
    ['vkvideo.ru',JSON.stringify({payload:{subs:{tr:{url:'/api/subtitle?id=4'}}}}),'/api/subtitle?id=4'],
    ['player.example.test',JSON.stringify({captions:{'pt-BR':'./captions?id=8'}}),'/config/captions?id=8'],
    ['film.example.test',JSON.stringify({tracks:[{kind:'captions',src:'../tr.vtt',label:'Turkce'}]}),'/tr.vtt']
  ]) {
    const h=pageHarness(host);h.win.fetch=async()=>captionResponse(`https://${host}/config/player.json`,body);h.load();
    await h.win.fetch(`https://${host}/config/player.json`);await flush();
    assert(h.posts.some(p=>p.__idmLinuxSubtitle&&p.url===`https://${host}${expected}`),host+' caption not discovered');
  }
  {
    const h=pageHarness('www.youtube.com');const body=JSON.stringify({events:[{tStartMs:1000,dDurationMs:2000,segs:[{utf8:'Merhaba dunya'}]}]});
    h.win.fetch=async()=>captionResponse('https://www.youtube.com/api/timedtext?lang=tr&fmt=json3',body);h.load();
    await h.win.fetch('https://www.youtube.com/api/timedtext?lang=tr&fmt=json3');await flush();
    const captured=h.posts.find(p=>p.__idmLinuxSubtitleText);
    assert(captured);assert(captured.vtt.startsWith('WEBVTT'));assert(captured.vtt.includes('00:00:01.000 --> 00:00:03.000'));assert.equal(captured.lang,'tr');
  }
  {
    const h=pageHarness();h.win.fetch=async()=>captionResponse('https://example.test/api',JSON.stringify({error:'login required'}));h.load();await h.win.fetch('https://example.test/api');await flush();
    assert(!h.posts.some(p=>p.__idmLinuxSubtitleText));
  }
  {
    const h=pageHarness('vkvideo.ru',false);h.win.fetch=async()=>captionResponse('https://vkvideo.ru/api',JSON.stringify({subs:[{url:'/api/subtitle?id=7'}]}));h.load();await h.win.fetch('https://vkvideo.ru/api');await flush();
    assert(!h.posts.some(p=>p.__idmLinuxSubtitle||p.__idmLinuxSubtitleText));
  }
  console.log('PASS OK/VK stringified metadata, relative external captions, JSON3 capture, invalid/passive rejection');
}
async function staleCaptionTests(){
  for(const mode of ['navigation','disable-enable']) {
    const h=pageHarness();let finish;
    h.win.fetch=async()=>({ok:true,url:'https://example.test/en.vtt',headers:{get:()=> 'text/vtt'},clone(){return this;},text:()=>new Promise(resolve=>{finish=resolve;})});
    h.load();await h.win.fetch('https://example.test/en.vtt');await until(()=>finish);
    if(mode==='navigation') h.location.href='https://example.test/watch?v=new';
    else {h.doc.documentElement.dataset.idmLinuxCaptureEnabled='0';h.fire('idm-linux-capture-state',{});h.doc.documentElement.dataset.idmLinuxCaptureEnabled='1';h.fire('idm-linux-capture-state',{});}
    finish('WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOld caption\n');await flush();
    assert(!h.posts.some(p=>p.__idmLinuxSubtitleText));
  }
  console.log('PASS delayed caption bodies cannot cross SPA navigation or disable/enable generation');
}
async function youtubeCaptionTimeoutTest(){
  const h=pageHarness('www.youtube.com');let calls=0,active=0;
  h.win.fetch=(url,init)=>new Promise((resolve,reject)=>{
    calls++;active++;
    init.signal.addEventListener('abort',()=>{active--;reject(new Error('timeout'));},{once:true});
  });
  h.context.setTimeout=(fn,ms)=>{const timer=setTimeout(fn,ms===8000?10:ms);timer.unref();return timer;};
  h.win.ytInitialPlayerResponse={videoDetails:{videoId:'abc'},captions:{playerCaptionsTracklistRenderer:{captionTracks:Array.from({length:9},(_,i)=>({baseUrl:'https://www.youtube.com/api/timedtext?v=abc&lang=l'+i,languageCode:'l'+i}))}}};
  h.load();h.context.fetch=h.win.fetch;await until(()=>calls===9&&active===0);
  assert(!h.posts.some(p=>p.__idmLinuxSubtitleText));
  console.log('PASS expired YouTube caption requests abort and release queue slots without emitting fake text');
}
async function youtubeCaptionQueueTests(){
  const h=pageHarness('www.youtube.com');const pending=[];let active=0,maxActive=0;
  h.win.fetch=(url,init={})=>new Promise((resolve,reject)=>{
    active++;maxActive=Math.max(maxActive,active);let settled=false;
    const done=()=>{if(settled)return;settled=true;active--;resolve(captionResponse(url,'WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nGood caption\n','text/vtt'));};
    pending.push({url,done});
    if(init.signal)init.signal.addEventListener('abort',()=>{if(!settled){settled=true;active--;reject(new Error('aborted'));}},{once:true});
  });
  const response=id=>({videoDetails:{videoId:id},captions:{playerCaptionsTracklistRenderer:{captionTracks:Array.from({length:25},(_,i)=>({baseUrl:'https://www.youtube.com/api/timedtext?v='+id+'&lang=l'+i,languageCode:'l'+i}))}}});
  h.win.ytInitialPlayerResponse=response('abc');h.load();h.context.fetch=h.win.fetch;await flush();
  assert.equal(pending.length,4);assert.equal(maxActive,4);
  while(pending.length<25){for(const p of pending)p.done();await flush();}
  for(const p of pending)p.done();await flush();assert.equal(maxActive,4);
  assert(h.posts.some(p=>p.__idmLinuxSubtitleText));
  h.posts.length=0;h.location.href='https://www.youtube.com/watch?v=new';h.fire('yt-navigate-start',{});h.fire('yt-navigate-finish',{});await flush();
  assert(!h.posts.some(p=>p.__idmLinuxSubtitle||p.__idmLinuxSubtitleText)); // stale initial response rejected
  h.win.ytInitialPlayerResponse=response('new');h.fire('yt-player-updated',{});await flush();
  const late=pending.slice(25);assert.equal(late.length,4);
  h.doc.documentElement.dataset.idmLinuxCaptureEnabled='0';h.fire('idm-linux-capture-state',{});await flush();
  assert.equal(active,0);const count=h.posts.filter(p=>p.__idmLinuxSubtitleText).length;
  for(const p of late)p.done();await flush();assert.equal(h.posts.filter(p=>p.__idmLinuxSubtitleText).length,count);
  console.log('PASS YouTube 25 captions use four concurrent requests; stale video response is rejected; disable aborts only own prefetch');
}
async function textTrackCaptionTests(){
  for(const mode of ['external','embedded','oversized']) {
    const h=pageHarness();
    const cue={startTime:0.123,endTime:0.456,text:'Full caption'};
    const tr={kind:'subtitles',label:'English',language:'en',cues:mode==='oversized'?Array(6001).fill(cue):[cue]};
    const video={textTracks:[tr],querySelectorAll:()=>mode==='external'?[{track:tr,src:'https://example.test/en.vtt'}]:[]};
    h.doc.querySelectorAll=selector=>selector==='video'?[video]:[];
    h.context.setTimeout=(fn,ms)=>{if(ms===2200){queueMicrotask(fn);return 1;}const t=setTimeout(fn,ms);t.unref();return t;};
    h.load();await flush();
    const captions=h.posts.filter(p=>p.__idmLinuxSubtitleText);
    assert.equal(captions.length,mode==='embedded'?1:0);
    if(captions.length)assert(captions[0].vtt.includes('00:00:00.123 --> 00:00:00.456'));
  }
  console.log('PASS external tracks avoid duplicate snapshots; embedded cues preserve milliseconds; oversize is not truncated');
}
async function arenaWorkspaceTests(){
  for (const mode of ['ok','truncated','reject','passive','unknown-size','cross-origin']) {
    const h=pageHarness('arena.ai',mode!=='passive',mode==='reject');const data=Buffer.alloc(1200000,43);let reads=0;
    h.win.fetch=async(url,init)=>({ok:true,headers:{get(k){return k==='content-length'?(mode==='unknown-size'?'':String(data.length)):k==='content-disposition'?"attachment; filename*=UTF-8''workspace%20source.zip":'application/zip';}},body:{getReader(){return {async read(){if(reads++)return {done:true};return {done:false,value:mode==='truncated'?data.subarray(0,8):data};},async cancel(){}};}}});
    h.load();const a=new h.Anchor();a.href=(mode==='cross-origin'?'https://other.test':'https://arena.ai')+'/api/chat/workspace/cas/user/opaque-key';a.click();
    if(mode==='ok') {
      await until(()=>h.posts.some(p=>p.action==='finish'));
      assert.equal(h.clicks.length,0);assert.equal(h.posts.find(p=>p.action==='begin').filename,'workspace source.zip');
      assert(Buffer.concat(h.chunks.map(p=>Buffer.from(p.dataBase64,'base64'))).equals(data));assert(h.chunks.every(p=>p.dataBase64.length<=524288));
    } else {
      await until(()=>h.clicks.length===1);assert(!h.posts.some(p=>p.action==='finish'));
      if(mode==='truncated'||mode==='reject')assert(h.posts.some(p=>p.action==='cancel'));
    }
  }
  console.log('PASS authenticated Arena row links stream via bounded runtime chunks; truncation, rejection, passive, unknown-size and cross-origin remain safe');
}
async function pageTests(){
  {
    const h=pageHarness('example.test',false);h.load();
    const blob=new Blob(['private']);const url=h.URL.createObjectURL(blob);const a=new h.Anchor();a.href=url;a.download='file.zip';a.click();
    assert.equal(h.clicks.length,1);assert.equal(h.posts.filter(p=>p.__idmLinuxBlobRequest).length,0);
    assert.equal(h.win.open('https://arena.ai/api/download/file').native,true);
    h.location.assign('https://arena.ai/chat/file');assert.equal(h.location.href,'https://arena.ai/chat/file');
    console.log('PASS passive Blob, Arena open and navigation remain native');
  }
  {
    const h=pageHarness();h.load();const data=Buffer.alloc(10*1024*1024+37,42);const blob=new Blob([data]);const url=h.URL.createObjectURL(blob);const a=new h.Anchor();a.href=url;a.download='large.zip';a.click();h.URL.revokeObjectURL(url);await until(()=>h.posts.some(p=>p.action==='finish'));
    assert.equal(h.clicks.length,0);assert(h.chunks.length>20);assert(h.chunks.every(p=>p.dataBase64.length<=524288));assert.equal(Buffer.concat(h.chunks.map(p=>Buffer.from(p.dataBase64,'base64'))).compare(data),0);
    assert.equal(h.posts.filter(p=>p.action==='finish').length,1);
    console.log('PASS 10 MiB Blob uses bounded chunks and a single finish');
  }
  {
    const h=pageHarness('example.test',true,true);h.load();const blob=new Blob(['authenticated contents']);const old=h.URL.createObjectURL(blob);const a=new h.Anchor();a.href=old;a.download='private.zip';a.click();h.URL.revokeObjectURL(old);await until(()=>h.clicks.length===1);
    assert.equal(h.clicks.length,1);assert.notEqual(h.clicks[0].url,old);assert.equal(h.clicks[0].blob,blob);assert.equal(h.clicks[0].filename,'private.zip');
    console.log('PASS rejected upload falls back once using a fresh retained Blob URL');
  }
  {
    const h=pageHarness();h.load();const url=h.URL.createObjectURL(new Blob(['x']));h.doc.documentElement.dataset.idmLinuxCaptureEnabled='0';h.doc.documentElement.dataset.idmLinuxBlobReady='0';const a=new h.Anchor();a.href=url;a.download='x.zip';a.click();assert.equal(h.clicks.length,1);assert.equal(h.posts.filter(p=>p.__idmLinuxBlobRequest).length,0);
    const mse=h.URL.createObjectURL({mediaSource:true});const m=new h.Anchor();m.href=mse;m.download='media.mp4';m.click();assert.equal(h.clicks.length,2);
    console.log('PASS live disable and unknown/MediaSource blob URLs are not cancelled');
  }
  {
    const h=pageHarness();h.load();h.win.onRpc=(d)=>{if(d.action==='chunk'){h.doc.documentElement.dataset.idmLinuxCaptureEnabled='0';h.doc.documentElement.dataset.idmLinuxBlobReady='0';h.fire('idm-linux-capture-state',{});}};
    const url=h.URL.createObjectURL(new Blob([Buffer.alloc(1024*1024,7)]));const a=new h.Anchor();a.href=url;a.download='pending.zip';a.click();h.URL.revokeObjectURL(url);await until(()=>h.clicks.length===1);
    assert.equal(h.posts.filter(p=>p.action==='finish').length,0);assert.equal(h.clicks.length,1);
    console.log('PASS disabling mid-upload produces one browser fallback and no native finish');
  }
  {
    const h=pageHarness();h.load();h.win.onRpc=(d)=>{if(d.action==='finish'){h.doc.documentElement.dataset.idmLinuxCaptureEnabled='0';h.doc.documentElement.dataset.idmLinuxBlobReady='0';}};
    const a=new h.Anchor();a.href=h.URL.createObjectURL(new Blob(['done']));a.download='accepted.zip';a.click();await until(()=>h.posts.some(p=>p.action==='finish'));assert.equal(h.clicks.length,0);
    console.log('PASS already-accepted finish ACK after disabling does not duplicate the browser download');
  }
  {
    const h=pageHarness('www.youtube.com');h.win.ytInitialPlayerResponse={streamingData:{formats:[{itag:18,url:'https://r1.googlevideo.com/videoplayback?itag=18',mimeType:'video/mp4'}]}};h.load();assert(h.posts.some(p=>p.__idmLinuxMediaHook&&p.url.includes('itag=18')));
    console.log('PASS YouTube source is emitted immediately, not lost to an out-of-scope function');
  }
  {
    const h=pageHarness('www.bilibili.com',false);h.win.__playinfo__={data:{dash:{video:[{baseUrl:'https://up.bilivideo.com/video.m4s'}],audio:[{baseUrl:'https://up.bilivideo.com/audio.m4s'}]}}};h.load();assert.equal(h.posts.filter(p=>p.__idmLinuxMediaHook).length,0);h.doc.documentElement.dataset.idmLinuxCaptureEnabled='1';h.doc.documentElement.dataset.idmLinuxBlobReady='1';h.fire('idm-linux-capture-state',{});assert.equal(h.posts.filter(p=>p.__idmLinuxMediaHook).length,2);
    console.log('PASS Bilibili sources survive late activation in the same open tab');
  }
}
function backgroundHarness(){
  const events={};const ev=n=>events[n]||(events[n]={listeners:[],addListener(fn){this.listeners.push(fn);}});
  const values={extDisabled:true};const cancelled=[],paused=[],resumed=[],replayed=[];let mode='reject',release;
  const state={ok:true,capture_downloads:true,video_bar_enabled:true,idm_installed:true,official_extension_connected:false,file_extensions:['ZIP'],excluded_domains:[]};
  const response=data=>({ok:true,status:200,json:async()=>data});
  const api={storage:{local:{get(keys,cb){const data={...values};if(cb){queueMicrotask(()=>cb(data));return;}return Promise.resolve(data);},set(data,cb){Object.assign(values,data);queueMicrotask(()=>{for(const fn of ev('storage').listeners)fn(Object.fromEntries(Object.entries(data).map(([k,v])=>[k,{newValue:v}])),'local');if(cb)cb();});}},onChanged:ev('storage')},
    runtime:{lastError:null,onMessage:ev('message'),onInstalled:ev('installed'),getManifest(){return{version:'1.0.0'};},sendNativeMessage(host,data,cb){cb({ok:false});}},
    webRequest:{onBeforeSendHeaders:ev('headers'),onHeadersReceived:ev('response'),onCompleted:ev('completed')},webNavigation:{onBeforeNavigate:ev('beforeNavigation'),onCompleted:ev('navigation'),onHistoryStateUpdated:ev('history')},
    tabs:{onRemoved:ev('tabRemoved'),onUpdated:ev('tabUpdated'),sendMessage(id,data,cb){if(cb)cb({ok:true});},query(q,cb){cb([]);}},
    cookies:{getAll(q,cb){cb([]);}},contextMenus:{onClicked:ev('menu'),removeAll(cb){cb();},create(){},update(){}},notifications:{create(){}},
    downloads:{onCreated:ev('created'),onDeterminingFilename:ev('filename'),pause(id,cb){paused.push(id);if(cb)cb();},cancel(id,cb){cancelled.push(id);if(cb)cb();},erase(q,cb){if(cb)cb();},removeFile(id,cb){if(cb)cb();},resume(id,cb){resumed.push(id);if(cb)cb();},download(q,cb){replayed.push(q);if(cb)cb();},search(q,cb){cb([]);}}};
  const context=vm.createContext({chrome:api,console,URL,Promise,AbortController,navigator:{userAgent:'test'},fetch:async(url)=>{if(String(url).includes('/api/download')){if(mode==='hold')return await new Promise(r=>release=()=>r(response({ok:true,takeover:true})));return response({ok:false});}return response(state);},setInterval(){return 1;},clearInterval(){},setTimeout(fn,ms){const t=setTimeout(fn,ms);t.unref();return t;},clearTimeout});
  vm.runInContext(fs.readFileSync(path.join(root,'background.js'),'utf8'),context);
  return {api,context,events,cancelled,paused,resumed,replayed,state,setMode(v){mode=v;},release(){release();},toggle(disabled){api.storage.local.set({extDisabled:disabled});},fire(item){for(const fn of ev('created').listeners)fn(item);}};
}
async function backgroundTests(){
  const h=backgroundHarness();await flush();h.fire({id:1,url:'https://arena.ai/api/file.zip',mime:'application/zip'});await flush();assert.equal(h.paused.length,0);assert.equal(h.cancelled.length,0);
  h.toggle(false);await flush();h.setMode('hold');h.fire({id:2,url:'https://files.example.test/archive.zip',mime:'application/zip'});await flush();assert(h.paused.includes(2));assert(!h.cancelled.includes(2));h.release();await flush();assert(h.cancelled.includes(2));
  h.setMode('reject');h.fire({id:3,url:'https://files.example.test/signed.zip?token=short',mime:'application/zip'});await flush();assert(h.resumed.includes(3));assert.equal(h.replayed.length,0);
  h.toggle(true);await flush();h.fire({id:4,url:'https://arena.ai/api/new.zip',mime:'application/zip'});await flush();assert(!h.paused.includes(4));assert(!h.cancelled.includes(4));
  console.log('PASS background passive listeners, pause-before-ACK, accepted purge and original-item resume');
}
async function navigationCaptionTest(){
  const h=backgroundHarness();await flush();h.toggle(false);await flush();
  let registered;
  for(const fn of h.events.message.listeners)fn({type:'IDM_REGISTER_CAPTURED_STREAMS',streams:[{url:'https://example.test/caption.vtt',mime:'text/vtt'}]},{tab:{id:41,url:'https://example.test/watch'},frameId:0},r=>{registered=r;});
  await until(()=>registered!==undefined);
  for(const fn of h.events.navigation.listeners)fn({tabId:41,frameId:0});
  assert.equal(vm.runInContext('tabStreams.get(41).size',h.context),1);
  for(const fn of h.events.beforeNavigation.listeners)fn({tabId:41,frameId:0});
  assert.equal(vm.runInContext('tabStreams.has(41)',h.context),false);
  console.log('PASS early captions survive navigation completion; next navigation clears stale captures');
}
async function probeRecoveryTest(){
  const h=backgroundHarness();await flush();h.toggle(false);await flush();
  vm.runInContext('globalThis.probeCalls=0;wakeDaemon=async()=>true;callBridge=async()=>++globalThis.probeCalls===1?{ok:false}:{ok:true,title:"Recovered",formats:[]};',h.context);
  let result;
  for(const fn of h.events.message.listeners)fn({type:'IDM_PROBE_VIDEO',pageUrl:'https://www.youtube.com/watch?v=fixture'}, {tab:{id:41,url:'https://www.youtube.com/watch?v=fixture',title:'fixture'},frameId:0}, r=>{result=r;});
  await until(()=>result!==undefined);
  assert.equal(result.ok,true);assert.equal(result.title,'Recovered');
  assert.equal(vm.runInContext('globalThis.probeCalls',h.context),2);
  console.log('PASS video probe recovers after bridge wake without assigning to const');
}
(async()=>{await arenaWorkspaceTests();await pageTests();await backgroundTests();await probeRecoveryTest();await externalCaptionTests();await textTrackCaptionTests();await staleCaptionTests();await youtubeCaptionQueueTests();await youtubeCaptionTimeoutTest();await navigationCaptionTest();console.log('BROWSER_CAPTURE_HARNESS_PASS');})().catch(e=>{console.error(e);process.exitCode=1;});
