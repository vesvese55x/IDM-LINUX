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
    XMLHttpRequest:XHR,fetch:win.fetch,console,navigator:{userAgent:'test'},setTimeout:timeout,clearTimeout,setInterval(){return 1;},clearInterval(){},MutationObserver:class{observe(){} disconnect(){}},performance:{getEntriesByType(){return[];}},btoa:s=>Buffer.from(s,'binary').toString('base64'),atob:s=>Buffer.from(s,'base64').toString('binary')});
  return {win,doc,location,context,clicks,posts,created,revoked,chunks,Anchor,URL:TestURL,fire,load(){vm.runInContext(fs.readFileSync(path.join(root,'page_hook.js'),'utf8'),context);}};
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
    webRequest:{onBeforeSendHeaders:ev('headers'),onHeadersReceived:ev('response'),onCompleted:ev('completed')},webNavigation:{onCompleted:ev('navigation'),onHistoryStateUpdated:ev('history'),onCommitted:ev('committed'),getAllFrames(q,cb){cb([]);}},
    tabs:{onRemoved:ev('tabRemoved'),onUpdated:ev('tabUpdated'),sendMessage(id,data,cb){if(cb)cb({ok:true});},query(q,cb){cb([]);}},
    cookies:{getAll(q,cb){cb([]);}},contextMenus:{onClicked:ev('menu'),removeAll(cb){cb();},create(){},update(){}},notifications:{create(){}},
    downloads:{onCreated:ev('created'),onDeterminingFilename:ev('filename'),pause(id,cb){paused.push(id);if(cb)cb();},cancel(id,cb){cancelled.push(id);if(cb)cb();},erase(q,cb){if(cb)cb();},removeFile(id,cb){if(cb)cb();},resume(id,cb){resumed.push(id);if(cb)cb();},download(q,cb){replayed.push(q);if(cb)cb();},search(q,cb){cb([]);}}};
  const context=vm.createContext({chrome:api,console,URL,Promise,AbortController,navigator:{userAgent:'test'},fetch:async(url)=>{if(String(url).includes('/api/download')){if(mode==='hold')return await new Promise(r=>release=()=>r(response({ok:true,takeover:true})));return response({ok:false});}return response(state);},setInterval(){return 1;},clearInterval(){},setTimeout(fn,ms){const t=setTimeout(fn,ms);t.unref();return t;},clearTimeout});
  context.importScripts = (name) => vm.runInContext(fs.readFileSync(path.join(root,name),'utf8'),context);
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
(async()=>{await pageTests();await backgroundTests();console.log('BROWSER_CAPTURE_HARNESS_PASS');})().catch(e=>{console.error(e);process.exitCode=1;});
