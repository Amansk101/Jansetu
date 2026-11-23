document.addEventListener('DOMContentLoaded',()=>{
  if(!window.Chart)return;
  const read=id=>{const el=document.getElementById(id);return el?{labels:(el.dataset.labels||'').split(',').filter(Boolean),values:(el.dataset.values||'').split(',').filter(Boolean).map(Number)}:{labels:[],values:[]};};
  const colors=['#167d9a','#39a6a3','#2e9d75','#e8a23a','#d9534f','#718fa4','#7769a8','#c48343'];
  const status=read('chartData'),statusEl=document.getElementById('statusChart');
  if(statusEl)new Chart(statusEl,{type:'doughnut',data:{labels:status.labels.map(x=>x.replaceAll('_',' ')),datasets:[{data:status.values,backgroundColor:colors,borderWidth:0,hoverOffset:5}]},options:{cutout:'68%',plugins:{legend:{position:'bottom',labels:{usePointStyle:true,padding:14}}}}});
  const category=read('categoryData'),categoryEl=document.getElementById('categoryChart');
  if(categoryEl)new Chart(categoryEl,{type:'bar',data:{labels:category.labels.map(x=>x.replaceAll('_',' ')),datasets:[{label:'Applications',data:category.values,backgroundColor:'#39a6a3',borderRadius:5}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true,ticks:{precision:0}},y:{grid:{display:false}}}}});
  const monthly=read('monthlyData'),monthlyEl=document.getElementById('monthlyChart');
  if(monthlyEl)new Chart(monthlyEl,{type:'line',data:{labels:monthly.labels,datasets:[{label:'Applications',data:monthly.values,borderColor:'#167d9a',backgroundColor:'#167d9a1c',fill:true,tension:.3,pointRadius:3}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{precision:0}}}}});
  const department=read('departmentData'),departmentEl=document.getElementById('departmentChart');
  if(departmentEl && department.values.length)new Chart(departmentEl,{type:'bar',data:{labels:department.labels,datasets:[{label:'Cases',data:department.values,backgroundColor:'#2e9d75',borderRadius:5}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{precision:0}}}}});
});
