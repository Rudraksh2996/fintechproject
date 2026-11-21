import type {Schema} from '../api/client';
export const usd=(n:number|string)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',notation:'compact',maximumFractionDigits:1}).format(Number(n));
export const pct=(n:number)=>new Intl.NumberFormat('en-US',{style:'percent',maximumFractionDigits:1}).format(n);
export const riskColor=(p:number)=>p>=.8?'#f38072':p>=.4?'#efb961':'#67c6ba';
export function inWindow(links:Schema['Link'][],from:number,to:number){return links.filter(l=>l.ts>=from && l.ts<=to)}
export function utc(ts:number){return new Date(ts*1000).toISOString().slice(0,10)}
export const isRecord=(v:unknown):v is Record<string,unknown>=>typeof v==='object' && v!==null && !Array.isArray(v);
