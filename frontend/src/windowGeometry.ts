import type {Room} from './types';

export function windowHeights(window:Room['windows'][number],room:Room){
 const height=window.height??Math.min(1.05,Math.max(.1,room.height-window.sillHeight-.1));
 const bottom=window.height===undefined||window.height===null?Math.max(0,Math.min(window.sillHeight,Math.max(0,room.height-height-.1))):window.sillHeight;
 return {bottom,height,top:bottom+height};
}

/** Width and elevation intervals on the same wall must both overlap. */
export function overlapsWindow(along:number,y:number,width:number,height:number,window:Room['windows'][number],room:Room,margin=0){
 const span=windowHeights(window,room);
 return Math.min(along+width/2,window.offset+window.width+margin)-Math.max(along-width/2,window.offset-margin)>1e-6&&
  Math.min(y+height,span.top+margin)-Math.max(y,span.bottom-margin)>1e-6;
}
