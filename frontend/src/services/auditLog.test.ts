import {beforeEach, describe, expect, it} from "vitest";
import {appendAuditLog, clearAuditLogs, listAuditLogs} from "../algorithm/auditLog";
describe("audit log",()=>{beforeEach(clearAuditLogs);it("creates and filters immutable-style event records",()=>{const row=appendAuditLog({entityType:"MODEL",entityId:"stacking-v1",action:"MODEL_EVALUATED",summary:"candidate checked",severity:"INFO",actor:"SYSTEM"});expect(row.id).toBeTruthy();expect(listAuditLogs({entityId:"stacking-v1"})).toHaveLength(1);expect(listAuditLogs({severity:"ERROR"})).toHaveLength(0)});});
