import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
import {chromium} from 'playwright-core';

const browser = await chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page = await browser.newPage({baseURL:'http://localhost:8080',viewport:{width:1440,height:1000}});
const errors=[];
page.on('pageerror',error=>errors.push(error.message));
const output=process.env.SCREENSHOTS_DIR??'/screenshots';
await mkdir(output,{recursive:true});
async function shot(name){await page.screenshot({path:output+'/'+name+'.png',animations:'disabled'});}
async function api(method,path,body){
  const res=await page.request.fetch('/api/v1/'+path,{method,data:body});
  assert.ok(res.ok(),method+' '+path+' returned '+res.status());
  return res.json();
}
async function liveAlert(){
  const configs=await api('GET','insider/configs');
  const active=configs.find(c=>c.is_active);
  const {id,is_active,...parameters}=active;
  assert.ok(is_active);
  const saved=await api('POST','insider/configs',{...parameters,name:'Release verification '+Date.now()});
  try{
    await api('POST','insider/configs/'+saved.id+'/activate');
    const job=await api('POST','insider/detect');
    const deadline=Date.now()+20000;
    let state=job;
    while(state.status==='running' && Date.now()<deadline){
      await new Promise(resolve=>setTimeout(resolve,200));
      state=await api('GET','insider/jobs/'+job.id);
    }
    assert.equal(state.status,'completed');
    const alerts=(await api('GET','insider/alerts?limit=100')).items.filter(a=>a.config_id===saved.id);
    assert.ok(alerts.length);
    const matching=alerts.map(a=>'.event a[href="/radar?id='+a.id+'"]').join(',');
    await page.locator(matching).first().waitFor();
  }finally{await api('POST','insider/configs/'+id+'/activate');}
}
// Find colored sphere interiors in the rendered canvas. Click in CSS pixels
// and require the application to select a real object returned by its API.
async function pickNode(key, valid){
  const canvas=page.locator('canvas').first();
  await canvas.waitFor();
  await canvas.scrollIntoViewIfNeeded();
  const deadline=Date.now()+45000;
  while(Date.now()<deadline){
    const png=(await canvas.screenshot()).toString('base64');
    const points=await page.evaluate(async base64=>{
      const img=await createImageBitmap(await (await fetch('data:image/png;base64,'+base64)).blob());
      const c=document.createElement('canvas');
      c.width=img.width;c.height=img.height;
      const ctx=c.getContext('2d');ctx.drawImage(img,0,0);
      const pixels=ctx.getImageData(0,0,c.width,c.height).data;
      const colored=(x,y)=>{
        const i=4*(y*c.width+x);
        const r=pixels[i],g=pixels[i+1],b=pixels[i+2];
        return Math.max(r,g,b)>90 && Math.max(r,g,b)-Math.min(r,g,b)>25;
      };
      const hits=[];
      for(let y=7;y<c.height-7;y+=3)for(let x=7;x<c.width-7;x+=3){
        if(colored(x,y)&&colored(x-2,y)&&colored(x+2,y)&&colored(x,y-2)&&colored(x,y+2)){
          if(!hits.some(p=>Math.abs(x-p.x)<8&&Math.abs(y-p.y)<8)) hits.push({x,y});
        }
      }
      img.close();
      return hits.sort((a,b)=>Math.abs(a.x-c.width/2)-Math.abs(b.x-c.width/2)).slice(0,25);
    },png);
    for(const point of points){
      await canvas.click({position:point,force:true});
      const value=new URL(page.url()).searchParams.get(key);
      if(value!==null && valid.has(Number(value)))return Number(value);
    }
    await page.waitForTimeout(150);
  }
  throw Error('Could not pick a rendered node for '+key);
}
try{
  await page.goto('/');
  const radar=await api('GET','insider/radar');
  const rings=await api('GET','mule/rings');
  assert.ok(radar.length && rings.length);
  await page.getByText('Alerts live',{exact:true}).waitFor();
  await page.getByText('Mule live',{exact:true}).waitFor();
  const counts=await page.locator('.kpis strong').allTextContents();
  assert.equal(Number(counts[0]),radar.length);assert.equal(Number(counts[2]),rings.length);
  await liveAlert();
  await shot('command-center');
  console.log('PASS command KPIs match APIs; committed detector alert visible on live feed');
  await page.goto('/radar');
  const activeAlerts=await api('GET','insider/radar');
  const alertId=await pickNode('id',new Set(activeAlerts.map(a=>a.id)));
  const detail=await api('GET','insider/alerts/'+alertId);
  await page.getByRole('heading',{name:new RegExp(detail.ticker+' · Filing detail')}).waitFor();
  await page.getByRole('link',{name:'Inspect Form 4'}).waitFor();
  await shot('insider-radar');
  console.log('PASS radar canvas node click opened matching filing detail');
  await page.goto('/mule');
  const selector=page.getByLabel('Candidate ring');
  const ring=rings[0].community;
  await selector.selectOption(String(ring));
  const graph=await api('GET','mule/rings/'+ring+'/graph');
  const count=page.locator('.explorer h2 small');
  await page.waitForFunction(n=>document.querySelector('.explorer h2 small')?.textContent?.includes('· '+n+' transfers'),graph.links.length);
  assert.equal(new URL(page.url()).searchParams.get('ring'),String(ring));
  const account=await pickNode('account',new Set(graph.nodes.map(n=>n.account_id)));
  await page.getByRole('heading',{name:'Account '+account,exact:true}).waitFor();
  await shot('mule-explorer');
  const before=await count.innerText();
  await page.getByRole('slider',{name:'Time window'}).press('Home');
  await page.waitForFunction(text=>document.querySelector('.explorer h2 small')?.textContent!==text,before);
  const shown=Number((await count.innerText()).match(/(\d+) transfers/)[1]);
  assert.ok(shown<graph.links.length);
  console.log('PASS isolated ring, picked member on canvas, inspected sidebar, scrubbed edges',graph.links.length,'->',shown);
  await page.goto('/research');
  const frame=page.frameLocator('iframe');
  await frame.getByRole('heading',{name:'Threshold Tuner',exact:true}).waitFor({timeout:45000});
  await frame.getByText('Qualifying clusters',{exact:true}).waitFor();
  await shot('workbench');
  assert.deepEqual(errors,[]);
  console.log('PASS embedded workbench; four screenshots saved; no browser exceptions');
}finally{await browser.close();}
