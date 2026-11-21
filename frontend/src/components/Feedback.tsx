import type {ReactNode} from 'react';
export function Feedback({loading,error,empty,children}:{loading:boolean;error:Error|null;empty?:boolean;children:ReactNode}){
 if(error)return <p role="alert" className="notice">{error.message}</p>;
 if(loading)return <p role="status" className="notice">Loading observations…</p>;
 if(empty)return <p className="notice">No observations match this view.</p>;
 return <>{children}</>;
}
