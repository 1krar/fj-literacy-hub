import test from 'node:test';
import assert from 'node:assert/strict';
import {parsePlan,makePrompt,planText,candidateSites,arithmeticPlan,consumeModelResults,catalogFromData,makeAnswerPrompt,parseAnswer,consumeAnswerResults,answerWarnings,formatErrorReport} from '../dist/assistant-core.mjs';
const sites=[{id:'cnki',name:'知网高级检索',url:'https://kns.cnki.net/kns8s/AdvSearch'}];
const step={id:'s1',title:'查找论文',source_id:'cnki',inputs:[{field:'篇名',value:'信息素养'}],conditions:['2025年'],find:['作者'],checks:['核对篇名'],depends_on:[],alternative_inputs:[]};
const plan={title:'论文作者题',question:'谁写了该论文？',mode:'retrieve',answer:'',explanation:'先查篇名',issues:[],steps:[step]};
test('valid route maps to trusted catalog URL',()=>{const p=parsePlan(JSON.stringify(plan),sites);assert.equal(p.steps[0].site.url,sites[0].url);assert.match(planText(p),/篇名：信息素养/);});
test('unknown AI site rejected',()=>assert.throws(()=>parsePlan(JSON.stringify({...plan,steps:[{...step,source_id:'https://evil.example'}]}),sites),/未收录/));
test('unresolved dependency rejected',()=>assert.throws(()=>parsePlan(JSON.stringify({...plan,steps:[{...step,depends_on:['s9']}]}),sites),/依赖/));
test('incomplete or oversized model reply rejected',()=>{assert.throws(()=>parsePlan('{"title":',sites));assert.throws(()=>parsePlan('x'.repeat(60001),sites));});
test('direct answer requires answer',()=>{assert.throws(()=>parsePlan(JSON.stringify({...plan,mode:'direct',steps:[]}),sites));const p=parsePlan(JSON.stringify({...plan,mode:'direct',answer:'42',steps:[]}),sites);assert.equal(p.answer,'42');});
test('fenced JSON accepted',()=>assert.equal(parsePlan('```json\n'+JSON.stringify(plan)+'\n```',sites).steps.length,1));
test('Gemini code block language label accepted without extracting arbitrary prose',()=>{assert.equal(parsePlan('JSON '+JSON.stringify(plan),sites).steps.length,1);assert.throws(()=>parsePlan('Here is a route: '+JSON.stringify(plan),sites));});
test('untrusted model markup remains text only',()=>assert.equal(parsePlan(JSON.stringify({...plan,title:'<script>alert(1)</script>'}),sites).title,'<script>alert(1)</script>'));
test('prompt has bounded relevant catalog',()=>{const large=Array.from({length:400},(_,i)=>({id:'r'+i,name:'网站'+i}));assert.equal(candidateSites(large,'题目').length,80);assert.match(makePrompt('RULES','题目',sites),/RULES/);});
test('arithmetic precedence and answer option',()=>assert.equal(arithmeticPlan('计算题：40÷5＋3×2 等于多少？A.11 B.14 C.22 D.48').answer,'B · 14'));
test('decimal calculation exact',()=>assert.equal(arithmeticPlan('计算：0.1+0.2=?').answer,'0.3'));
test('parentheses and unary negatives',()=>assert.equal(arithmeticPlan('(-2+3)*4=?').answer,'4'));
test('nonterminating fraction preserved',()=>assert.equal(arithmeticPlan('1/3=?').answer,'1/3'));
test('division by zero explicit',()=>assert.match(arithmeticPlan('2/0=?').answer,/无定义/));
test('word problems and code never evaluated as arithmetic',()=>{assert.equal(arithmeticPlan('一个正方形边长6厘米，面积是多少？'),null);assert.equal(arithmeticPlan('alert(1)+2=?'),null);});
test('deep arithmetic exceeds bounded grammar',()=>assert.equal(arithmeticPlan('('.repeat(30)+'1+2'+')'.repeat(30)+'=?'),null));

test('image-only questions retain authoritative competition entry points',()=>{const crowded=Array.from({length:150},(_,i)=>({id:'course'+i,name:'知网标准专利课程'+i}));crowded.push({id:'r-r059',name:'全国标准信息平台'},{id:'r-r067',name:'中国专利公布公告'});const ids=candidateSites(crowded,'请识别合成截图题目').map(s=>s.id);assert.ok(ids.includes('r-r059'));assert.ok(ids.includes('r-r067'));assert.equal(ids.length,80);});

test('fast model result is usable before slow model finishes',()=>{const state={plans:{},errors:{},chosen:''};consumeModelResults(state,{deepseek:{state:'completed',text:JSON.stringify(plan),completed_at:1}},sites);assert.equal(state.chosen,'deepseek');assert.equal(state.plans.deepseek.steps.length,1);assert.equal(state.plans.gemini,undefined);});
test('late response preserves selection and edited first route',()=>{const state={plans:{},errors:{},chosen:''};const early={state:'completed',text:JSON.stringify(plan),completed_at:1};consumeModelResults(state,{deepseek:early},sites);state.plans.deepseek.steps[0].inputs[0].value='用户已修改';consumeModelResults(state,{deepseek:early,gemini:{...early,completed_at:2}},sites);assert.equal(state.chosen,'deepseek');assert.equal(state.plans.deepseek.steps[0].inputs[0].value,'用户已修改');assert.ok(state.plans.gemini);});
test('bad first response does not block valid second response',()=>{const state={plans:{},errors:{},chosen:''};consumeModelResults(state,{gemini:{state:'completed',text:'invalid'},deepseek:{state:'completed',text:JSON.stringify(plan)}},sites);assert.equal(state.chosen,'deepseek');assert.match(state.errors.gemini,/格式无效/);});

test('saved standard source alias maps to the new official entry',()=>{const data={resources:[{id:'r059',name:'国家标准全文公开系统',url:'https://openstd.samr.gov.cn/bzgk/std/',aliases:['r060']}]};const mapped=catalogFromData(data,{folders:[]});const old=parsePlan(JSON.stringify({...plan,steps:[{...step,source_id:'r-r060'}]}),mapped);assert.equal(old.steps[0].site.url,data.resources[0].url);assert.equal(candidateSites(mapped,'标准').some(s=>s.id==='r-r060'),false);});


const directAnswer={answer:'B · 14',explanation:'40/5+3*2=14',suitability:'direct',confidence:'high',warnings:[],checks:[]};
test('answer parser rejects incomplete and unsupported reliability fields',()=>{assert.throws(()=>parseAnswer('{"answer":'));assert.throws(()=>parseAnswer(JSON.stringify({...directAnswer,confidence:'99%'})));assert.throws(()=>parseAnswer(JSON.stringify({...directAnswer,answer:''})));assert.equal(parseAnswer('```json\n'+JSON.stringify(directAnswer)+'\n```').answer,'B · 14');});
test('unsuitable question may abstain without inventing answer',()=>{const a=parseAnswer(JSON.stringify({...directAnswer,answer:'',suitability:'unsuitable',confidence:'low'}));assert.match(answerWarnings(a,'clarify').join(' '),/不适合/);assert.match(answerWarnings(a,'clarify').join(' '),/把握较低/);});
test('retrieval route always requires verification even if model claims high confidence',()=>{assert.match(answerWarnings(directAnswer,'retrieve').join(' '),/不能代替数据库/);});
test('fast answer appears first and later result preserves user selection',()=>{const state={answers:{},errors:{},chosen:''};consumeAnswerResults(state,{deepseek:{state:'completed',text:JSON.stringify(directAnswer),completed_at:10},gemini:{state:'running'}});assert.equal(state.chosen,'deepseek');state.chosen='deepseek';consumeAnswerResults(state,{gemini:{state:'completed',text:JSON.stringify({...directAnswer,answer:'A'}),completed_at:20}});assert.equal(state.chosen,'deepseek');assert.match(answerWarnings(directAnswer,'direct',state.answers).join(' '),/答案文本不同/);});
test('malformed model answer never replaces valid sibling result',()=>{const state={answers:{},errors:{},chosen:''};consumeAnswerResults(state,{gemini:{state:'completed',text:'not json',completed_at:1},deepseek:{state:'completed',text:JSON.stringify(directAnswer),completed_at:2}});assert.equal(state.chosen,'deepseek');assert.ok(state.errors.gemini);});
test('direct-answer prompt requests abstention and passes full recognized question',()=>{const p=makeAnswerPrompt('当前标准状态？A现行 B废止','retrieve');assert.match(p,/不生成检索路线/);assert.match(p,/未核实不得给出确定结论/);assert.match(p,/当前标准状态？A现行 B废止/);});

test('same option with explanatory number is not treated as disagreement',()=>{assert.equal(answerWarnings(directAnswer,'direct',{gemini:{...directAnswer,answer:'B'},deepseek:{...directAnswer,answer:'B.14'}}).length,0);});

test('error report excludes question and redacts credential-like error content',()=>{const text=formatErrorReport('route',{models:['gemini'],time:'now',message:'GET https://example.com/error?token=secret session=private Bearer hidden',errors:{gemini:'invalid JSON'},question:'private question'});assert.match(text,/invalid JSON/);assert.doesNotMatch(text,/private|secret|Bearer hidden/);assert.match(text,/已隐藏/);});
