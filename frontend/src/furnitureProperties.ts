import {clone,type CatalogItem,type FurnitureProperties} from './types';

export function completeFurnitureProperties(properties:FurnitureProperties,catalog:CatalogItem[]):FurnitureProperties{
 const result=clone(properties),template=catalog.find(item=>item.category===result.category);
 if(!template)return result;
 result.label=result.label?.trim()||template.label;
 result.frontDirection=result.frontDirection||(template.category.includes('bed')?'negative_z':'positive_z');
 for(const dimension of ['width','depth','height'] as const){
  if(result[dimension]===null){
   result[dimension]=template[dimension];
   result.dimensionSources[dimension]='template';
   result.evidence[dimension]='类别模板';
  }
 }
 return result;
}
