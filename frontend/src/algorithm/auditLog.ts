import type {AuditLogEntry} from "../types";
const store:AuditLogEntry[]=[];
export const createAuditLogEntry=(input:Omit<AuditLogEntry,"id"|"createdAt">&Partial<Pick<AuditLogEntry,"id"|"createdAt">>):AuditLogEntry=>({...input,id:input.id??`audit-${store.length+1}`,createdAt:input.createdAt??new Date().toISOString()});
export const appendAuditLog=(input:AuditLogEntry|Parameters<typeof createAuditLogEntry>[0])=>{const entry="id" in input&&"createdAt" in input?input as AuditLogEntry:createAuditLogEntry(input);store.push(entry);return entry};
export const listAuditLogs=(filter:{entityType?:string;entityId?:string;severity?:string;startTime?:string;endTime?:string}={})=>store.filter(row=>(!filter.entityType||row.entityType===filter.entityType)&&(!filter.entityId||row.entityId===filter.entityId)&&(!filter.severity||row.severity===filter.severity)&&(!filter.startTime||row.createdAt>=filter.startTime)&&(!filter.endTime||row.createdAt<=filter.endTime));
export const clearAuditLogs=()=>{store.splice(0)};
