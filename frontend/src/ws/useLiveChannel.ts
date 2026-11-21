import {useEffect} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {create} from 'zustand';
import {isRecord} from '../lib/display';

type Channel='alerts'|'mule';
type State='connecting'|'live'|'offline';
type Event={type:'cluster_alert'|'account_scored'|'ring_detected';id:number;label:string;value:number};
export function parseEvent(raw:string):Event|'heartbeat'|null{
  let value:unknown;try{value=JSON.parse(raw)}catch{return null}
  if(!isRecord(value)||value.version!==1)return null;
  if(value.type==='heartbeat' && typeof value.ts==='string') return 'heartbeat';
  const p=value.payload;if(!isRecord(p))return null;
  if(value.type==='cluster_alert' && typeof p.id==='number' && typeof p.ticker==='string' && typeof p.conviction_score==='string' && Number.isFinite(Number(p.conviction_score)))return {type:value.type,id:p.id,label:p.ticker,value:Number(p.conviction_score)};
  if(value.type==='account_scored' && typeof p.account_id==='number' && typeof p.probability==='number')return {type:value.type,id:p.account_id,label:`Account ${p.account_id}`,value:100*p.probability};
  if(value.type==='ring_detected' && typeof p.community==='number' && typeof p.risk==='number')return {type:value.type,id:p.community,label:`Ring ${p.community}`,value:p.risk};
  return null;
}
export const retryDelay=(n:number)=>Math.min(30000,500*2**Math.min(n,6));
type Live={status:Record<Channel,State>;events:(Event & {time:number})[]};
export const useLive=create<Live>(()=>({status:{alerts:'connecting',mule:'connecting'},events:[]}));
export function useLiveChannel(channel:Channel){
  const cache=useQueryClient();
  useEffect(()=>{
    let closed=false,attempt=0,timer=0,ws:WebSocket;
    const status=(s:State)=>useLive.setState(v=>({status:{...v.status,[channel]:s}}));
    function open(){
      status('connecting');
      ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${channel}`);
      ws.onopen=()=>{attempt=0;status('live')};
      ws.onmessage=({data}:MessageEvent<unknown>)=>{
        if(typeof data!=='string')return;
        const event=parseEvent(data);
        if(!event||event==='heartbeat')return;
        useLive.setState(v=>({events:[{...event,time:Date.now()},...v.events].slice(0,100)}));
        void cache.invalidateQueries({queryKey:[channel==='alerts'?'insider':'mule']});
      };
      ws.onclose=()=>{if(!closed){status('offline');timer=window.setTimeout(open,retryDelay(attempt++))}};
    }
    open();return ()=>{closed=true;clearTimeout(timer);ws.close()};
  },[channel,cache]);
}
