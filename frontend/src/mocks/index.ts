// 统一 Mock：字段形状必须与 docs/api-contract.md v1.4 一致。
// 关闭 Mock（VITE_USE_MOCK=false）后页面取数不应变形。
const cite={source_name:'演示数据（非官方）',source_url:'https://example.invalid/mock',year:2026,snippet:'仅用于前端交互演示，不代表政策或招生事实。'}
const now='2026-10-12T09:00:00+08:00'
// 契约 5：志愿条目 PlanItem（tier / order / school_id / school_name / group_code / major_ids / major_names / min_score_ref / min_rank_ref / ref_year / gap_rank / source_note）
const planItems=[
 {tier:'冲',order:1,school_id:'demo-1',school_name:'演示院校甲',group_code:'01',major_ids:['major-1'],major_names:['计算机科学与技术'],min_score_ref:632,min_rank_ref:12000,ref_year:2025,gap_rank:-6000,source_note:'演示数据（非官方）',...cite},
 {tier:'稳',order:1,school_id:'demo-2',school_name:'演示院校乙',group_code:'02',major_ids:['major-2'],major_names:['软件工程'],min_score_ref:620,min_rank_ref:18000,ref_year:2025,gap_rank:0,source_note:'演示数据（非官方）',...cite},
 {tier:'稳',order:2,school_id:'demo-3',school_name:'演示院校丙',group_code:'03',major_ids:['major-3'],major_names:['网络工程'],min_score_ref:616,min_rank_ref:21000,ref_year:2025,gap_rank:3000,source_note:'演示数据（非官方）',...cite},
 {tier:'保',order:1,school_id:'demo-4',school_name:'演示院校丁',group_code:'04',major_ids:['major-1','major-2'],major_names:['计算机科学与技术','软件工程'],min_score_ref:598,min_rank_ref:42000,ref_year:2025,gap_rank:24000,source_note:'演示数据（非官方）',...cite}
]
// 管理端·审核任务项 = review.task_item（列表与详情共用同一形状）
const adminReviewTask={task_id:1,qa_log_id:101,question:'示例问题：620 分能报哪些专业？',answer:'示例回答（演示数据，不代表招生事实）。',confidence:'low',trigger_reason:'低置信、涉规则',status:'pending',reviewer:null,created_at:now}
export const fixtures={ auth:{login:{token:'mock-token',expires_in:86400,user:{user_id:'u-demo',username:'demo',role:'user'}},admin:{token:'mock-admin-token',expires_in:86400,admin:{admin_id:'a-demo',username:'admin',role:'admin'}},error:{code:1002,message:'用户名或密码错误',data:null,trace_id:'mock-auth-error'}},
 // 契约 2：GET/PUT /api/user/profile 的 data 为完整 Profile，并附 completeness{percent,missing}
 profile:{profile:{profile_id:1,province:'河南',exam_type:'普通',first_subject:'物理',second_subjects:['化学','生物'],subject_type:'物理类',score:620,rank:18000,household_type:'农村',home_county:'示例县',home_county_code:'000000',school_years:3,enrollment_county:null,household_years:3,enrollment_years:3,parent_household_local:true,has_national_special:false,has_local_special:false,has_college_special:false,special_marks:[],preferred_cities:['郑州','武汉'],preferred_majors:['计算机类'],tuition_budget:15000,batch_preference:['本科批'],accept_adjustment:true,updated_at:now,completeness:{percent:42,missing:['color_vision','vision_left','vision_right','height','weight','hepatitis_b','hearing','smell','stutter']}},empty:null},
 // 契约 3：pathway_id 为字符串 slug；data_status 取 available|partial|schema_only|unavailable
 pathways:{items:[{id:'regular-batch',pathway_id:'regular-batch',name:'普通批',category:'普通类',batch:'本科批',target_group:'普通高考考生',apply_time:'以当年官方安排为准',priority:'P0',status:'available',data_status:'available',sources:[cite]},{id:'national-plan',pathway_id:'national-plan',name:'国家专项计划',category:'专项类',batch:'本科批',target_group:'符合政策条件的考生',apply_time:'以当年官方安排为准',priority:'P0',status:'schema_only',data_status:'schema_only',sources:[cite]}],detail:{pathway_id:'national-plan',name:'国家专项计划',category:'专项类',batch:'本科批',target_group:'符合政策条件的考生',apply_time:'以当年官方安排为准',priority:'P0',data_status:'schema_only',evaluable:false,description:'此为演示内容。资格以官方审核为准。',conditions:[{text:'需核对户籍与学籍条件',source_name:cite.source_name,source_url:cite.source_url}],timeline:[{node:'报名',date_desc:'以官方安排为准'}],sources:[cite],citations:[cite]},regions:{province:'河南',data_status:'schema_only',regions:[{province:'河南',program:'national',program_name:'国家专项计划',scope:'county_list',verified:false,expected_count:38,counties:[],definition:'演示定义，非官方名单。',citation:cite}],citations:[cite],missing_rule_sets:['pathway_region']}},
 // 契约 8.4：data 为 {data_status, items[], summary, missing_rule_sets}
 // 演示单元覆盖四种叙事：① 有风险+待核验 ② 体检被退档（后果最重）③ 选科报不了 ④ 无规则数据（兜底态）
 eligibility:{data:{data_status:'schema_only',items:[{unit_id:'henan-ug-demo-01',school_name:'演示院校甲',eligible:null,blockers:[],warnings:[{type:'fee',level:'soft',detail:'年学费预算低于该专业演示学费，存在超预算风险。',major_ids:['major-1'],major_names:['计算机科学与技术'],citation:cite}],unknowns:[{type:'physical',level:'unknown',detail:'未填写体检结论，相关身体限制待核验。',fields:['color_vision']}],citations:[cite]},{unit_id:'henan-ug-demo-02',school_name:'演示院校戊',eligible:false,blockers:[{type:'physical',level:'reject',detail:'裸眼视力不满足该专业录取体检要求。',major_ids:['major-5'],major_names:['飞行技术'],citation:cite}],warnings:[],unknowns:[],citations:[cite]},{unit_id:'henan-ug-demo-03',school_name:'演示院校乙',eligible:false,blockers:[{type:'subject',level:'reject',detail:'首选科目不符合该专业组的选科要求。',major_ids:['major-2'],major_names:['临床医学'],citation:cite}],warnings:[],unknowns:[],citations:[cite]},{unit_id:'henan-ug-demo-04',school_name:'演示院校己',eligible:null,blockers:[],warnings:[],unknowns:[],citations:[]}],summary:{total:4,blocked:2,warned:1,unknown:1},missing_rule_sets:['province_exam_rule','subject_requirement']}},
 // 契约 4：confidence 为 0~1 数值，confidence_level 为 high|medium|low；low 供「无来源+低置信」空态演示
 qa:{answer:{qa_log_id:101,session_id:'session-demo',question:'620分能报哪些专业？',answer:'这是演示回答。正式结论应以官方政策原文为准。[1]',citations:[{...cite,index:1,chunk_id:'mock-chunk'}],confidence:0.72,confidence_level:'medium',needs_review:false,degraded:false,elapsed_ms:480},low:{qa_log_id:102,session_id:'session-demo',question:'这个专业今年会涨分吗？',answer:'当前资料不足，建议人工核实。',citations:[],confidence:0.18,confidence_level:'low',needs_review:true,degraded:true,elapsed_ms:8000},history:{items:[{qa_log_id:102,session_id:'session-demo',question:'这个专业今年会涨分吗？',answer:'当前资料不足，建议人工核实。',confidence:'low',citations:[],needs_review:true,degraded:true,created_at:now},{qa_log_id:101,session_id:'session-demo',question:'620分能报哪些专业？',answer:'这是演示回答。正式结论应以官方政策原文为准。[1]',confidence:'medium',citations:[{...cite,index:1,chunk_id:'mock-chunk'}],needs_review:false,degraded:false,created_at:now}],total:2,page:1,page_size:20}},
 // 契约 5/6.1：tiers 为各档实际数量 Record<string,number>，志愿条目在 items[]，按 item.tier 分组
 recommendation:{strategy:'major',priority:'专业优先',tiers:{冲:1,稳:2,保:1},quota:{冲:2,稳:4,保:3},items:planItems,risk_notes:['演示方案未接入真实分数库，仅供交互演示。'],excluded:[],shortage:[{tier:'冲',expected:2,actual:1,reason:'演示候选中符合冲档的院校不足，不硬凑。'}],citations:[cite],data_status:'schema_only',summary:'演示方案：冲 1 / 稳 2 / 保 1。',disclaimer:'演示数据不构成填报建议。',generated_at:now},
 // 契约 6 / 6.1：GET /api/schools 与 /api/majors 返回分页包 {items,total,page,page_size}
 school:{list:{items:[{school_id:'demo-1',name:'演示院校甲',code:'00001',province:'河南',city:'郑州',level:'本科',type:'综合',ownership:'公办',intro:'此为演示内容。',sources:[cite],citations:[cite]}],total:1,page:1,page_size:20},detail:{school_id:'demo-1',name:'演示院校甲',code:'00001',province:'河南',city:'郑州',level:'本科',type:'综合',ownership:'公办',intro:'此为演示内容。',citations:[cite]},profile:{available:false,tuition_range:'待官方数据接入',accommodation_fee:null,campus_list:[],established_year:null,master_phd_points:null,first_class_major_count:null,faculty_count:null,student_faculty_ratio:null,source_note:'演示数据（非官方）',citations:[cite]},life:{items:[{category:'校园生活',content:'演示生活信息',source_type:'公开网络',source_name:cite.source_name,source_url:cite.source_url,year:cite.year,reliability:'low'}]}},
 majors:{list:{items:[{major_id:'demo-major',name:'计算机类',code:'0809',category:'工学',degree:'工学学士',intro:'演示专业介绍',first_class_schools:['演示院校甲']}],total:1,page:1,page_size:20},detail:{major_id:'demo-major',name:'计算机类',code:'0809',category:'工学',degree:'工学学士',intro:'演示专业介绍',first_class_schools:['演示院校甲']}},
 favorites:{items:[{favorite_id:1,target_type:'school',target_id:'demo-1',target_name:'演示院校甲',created_at:now}]},plans:{items:[],detail:{plan_id:1,name:'我的演示方案',strategy:'major',items:planItems}},
 // 管理端 fixtures：形状与后端真实 DTO 一一对应（corpus.doc_item / indexing.task_state /
 // pathway_admin.* / review.task_item / stats.overview / rule_admin.*），关闭 Mock 后页面不变形。
 admin:{
  // 语料列表项 = corpus.doc_item（doc_id/title/source_name/source_url/year/doc_type/province/pathway_id/chunk_count/created_at）
  docs:{items:[{doc_id:1,title:'河南省 2026 年普通高校招生工作规定（演示）',source_name:cite.source_name,source_url:cite.source_url,year:2026,doc_type:'政策',province:'河南',pathway_id:'regular-batch',chunk_count:3,created_at:now}],total:1,page:1,page_size:20},
  // 索引任务 = indexing.task_state（progress 为对象，非数字）
  indexTask:{task_id:1,status:'completed',progress:{total:120,processed:120,embedded:96,pending_embedding:0,failed:0,percent:100},scope:'all',doc_ids:[],incremental:true,message:'演示：向量化由索引服务负责。',embedder_ready:false,operator:'admin',created_at:now,started_at:now,finished_at:now},
  // 途径字典项 = pathway_admin.pathway_item（source 为来源三要素对象）
  pathways:[{pathway_id:'regular-batch',name:'普通批',category:'普通类',batch:'本科批',target_group:'普通高考考生',apply_time:'以当年官方安排为准',description:'演示条目，资格以官方审核为准。',priority:'P0',data_status:'available',year:2026,source:cite},{pathway_id:'national-plan',name:'国家专项计划',category:'专项类',batch:'本科批',target_group:'符合政策条件的考生',apply_time:'以当年官方安排为准',description:'演示条目。',priority:'P0',data_status:'schema_only',year:2026,source:cite}],
  // 资格规则项 = pathway_admin.rule_item
  pathwayRules:[{rule_id:1,pathway_id:'national-plan',province:'河南',rule_type:'户籍',rule_desc:'考生本人具有实施区域当地连续 3 年以上户籍，其父亲或母亲或法定监护人具有当地户籍（演示）。',params:{},year:2026,source:cite}],
  // 专项实施区域项 = pathway_admin.region_item
  regions:[{region_id:1,pathway_id:'national-plan',province:'河南',county_name:'固始县',county_code:'411525',year:2026,source_name:cite.source_name,source_url:cite.source_url}],
  // 审核列表/详情 = review.task_item(+detail 追加字段)
  reviewList:{items:[adminReviewTask],total:1,page:1,page_size:20},
  reviewDetail:{...adminReviewTask,citations:[{...cite,index:1,chunk_id:'mock-chunk'}],degraded:true,session_id:'session-demo',user_id:null,original_answer:adminReviewTask.answer,corrected_answer:null,comment:null,reviewed_at:null,qa_created_at:now},
  // 统计 = stats.overview
  stats:{doc_count:1,chunk_count:3,qa_count:12,low_confidence_count:2,review_pending_count:1,coverage_by_pathway:[{pathway_id:'regular-batch',pathway_name:'普通批',priority:'P0',doc_count:1,chunk_count:3,covered:true},{pathway_id:'national-plan',pathway_name:'国家专项计划',priority:'P0',doc_count:0,chunk_count:0,covered:false}]},
  // 契约 8.8：规则集状态（rule_admin.rule_dataset_status_item）与五组规则列表（分页包）
  ruleDatasetStatus:{items:[
   {rule_id:1,province_code:'41',year:2026,batch_code:'undergraduate_regular',exam_type:'普通',dataset:'province_exam_rule',status:'available',note:'由导入/维护覆盖率校验自动得出（契约 8.8）。',updated_at:now},
   {rule_id:2,province_code:'41',year:2026,batch_code:'undergraduate_regular',exam_type:'普通',dataset:'subject_requirement',status:'unavailable',note:'选科要求数据尚未导入。',updated_at:now},
   {rule_id:3,province_code:'41',year:2026,batch_code:'undergraduate_regular',exam_type:'普通',dataset:'physical_restriction',status:'unavailable',note:'体检限制映射表尚未建立。',updated_at:now}
  ],total:3,page:1,page_size:20},
  ruleProvinceRules:{items:[{rule_id:1,province_code:'41',province:'河南',year:2026,batch_code:'undergraduate_regular',batch:'本科批',exam_type:'普通',mode:'group',volunteer_count:45,majors_per_group:6,has_adjust:true,admit_method:'parallel',ratio:'1:1',tie_rule:'同分依次比较语文数学外语（演示）。',mutex_groups:[],collect_count:null,source:cite}],total:1,page:1,page_size:20},
  ruleEmpty:{items:[],total:0,page:1,page_size:20}
 }
}
