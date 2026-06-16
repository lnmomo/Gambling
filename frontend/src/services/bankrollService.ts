import type {BankrollConfig,BankrollTransaction} from "../types";
import {createDefaultBankrollConfig} from "../algorithm/bankrollManager";
const config=createDefaultBankrollConfig();
const transactions:BankrollTransaction[]=[];
export const getBankrollConfig=():BankrollConfig=>config;
export const listBankrollTransactions=()=>[...transactions];
export function appendBankrollTransaction(row:Omit<BankrollTransaction,"id"|"createdAt">):BankrollTransaction{const tx={...row,id:`bankroll-${transactions.length+1}`,createdAt:new Date().toISOString()};transactions.push(tx);config.currentBankroll=tx.bankrollAfter;config.updatedAt=tx.createdAt;return tx}
