(() => {
"use strict";
const $ = s => document.querySelector(s);
const html = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const linkify = value => html(value).replace(/https?:\/\/[^\s<]+[^\s<.,;:!?)"']/g, url => '<a href="'+url+'" target="_blank" rel="noopener noreferrer">'+url.replace(/^https?:\/\/(www\.)?/,"").replace(/\/$/,"")+'</a>');
const srcset = p => ' srcset="'+html(p.thumb)+' '+Math.min(640,p.width||640)+'w, '+html(p.src)+' '+(p.width||1400)+'w" sizes="(max-width: 700px) 100vw, 700px"'+(p.width&&p.height?' width="'+p.width+'" height="'+p.height+'"':"");
const section = (r,kind) => (r.sections||[]).find(s=>s.kind===kind);
const KASHRUT = {"meat":"Meat","dairy":"Dairy","pareve":"Pareve","fish":"Fish · Pareve"};
const COURSES = {"mains":"Main","soups":"Soup","salads":"Salad","sides":"Side","starters":"Starter","breakfast":"Breakfast","desserts":"Dessert","snacks":"Snack","sauces":"Sauce & dressing","guides":"Kitchen guide"};
const group = r => KASHRUT[r.kashrut] ? r.kashrut : "pareve";
const label = r => KASHRUT[group(r)];
const from = r => r.cooks && r.cooks.length ? r.cooks.slice(0,2).join(" & ")+(r.cooks.length>2?" +":"") : "";
const emoji = r => {
 const t = r.title.toLowerCase();
 if (/soup|chamin|chulent|chollent|stew|chili|chowder/.test(t)) return "🍲";
 if (/salad|slaw|matbucha|tznon|bishbash/.test(t)) return "🥗";
 if (/cake|tiramisu|quiche|cheesecake/.test(t)) return "🍰";
 if (/cookie|mandelbroit|bars|squares|hamatashen|doughnut|cream puff|balls|popcorn/.test(t)) return "🍪";
 if (/pie|muffin|pear/.test(t)) return "🥧";
 if (/kugel|pashtida|casserole|ziti|lasagna/.test(t)) return "🥘";
 if (/latke|pancake|blintz|french toast|toast|egg|shakshouka/.test(t)) return "🍳";
 if (/noodle|spaghetti|macaroni|mac and cheese|gnocchi|varnishkes|pasta/.test(t)) return "🍝";
 if (/bureka|dough/.test(t)) return "🥐";
 if (/rice|couscous|kasha/.test(t)) return "🍚";
 if (/potato|pastellot|sweet potato/.test(t)) return "🥔";
 if (/dressing|sauce|mayonnaise|rub|spice|charoset|marror|chutney|relish/.test(t)) return "🫙";
 if (/artichoke|fennel|carrot|beet|broccoli|zucchini|spinach|tomato|mushroom|eggplant/.test(t)) return "🥦";
 if (group(r)==="fish") return "🐟";
 if (/chicken|schnitzel|hens|wings|duck/.test(t)) return "🍗";
 if (group(r)==="meat") return "🥩";
 if (group(r)==="dairy") return "🧀";
 return "🫒";
};
const storeKey = "ashkesephard-saved";
let saved;
try { saved = new Set(JSON.parse(localStorage.getItem(storeKey) || "[]")); } catch { saved = new Set(); }
let recipes=[], type="all", search="", sort="new", cook="", kashrut="", savedOnly=false, shown=12, active=null, priorFocus=null;
const searchIndex = new Map();
function indexText(r) {
 return [r.title,r.summary,(r.cooks||[]).join(" "),(r.labels||[]).join(" "),COURSES[r.courses[0]]||"",label(r),
  ...(r.sections||[]).flatMap(s=>s.items.map(i=>i.text)),...(r.photos||[]).map(p=>p.caption||"")].join(" ").toLowerCase();
}
function matches(r) {
 if (type==="shabbat" ? !r.shabbat : type==="holiday" ? !r.holiday : type==="gf" ? !r.gluten_free : type!=="all" && !r.courses.includes(type)) return false;
 if (cook && !(r.cooks||[]).includes(cook)) return false;
 if (kashrut && group(r)!==kashrut) return false;
 if (savedOnly && !saved.has(r.slug)) return false;
 return !search || search.split(/\s+/).every(word=>searchIndex.get(r.slug).includes(word));
}
function status(r) {
 if (r.in_progress) return "◌ Still being written up";
 if (r.shabbat) return "✳ Shabbat table";
 if (r.holiday) return "✳ For the chagim";
 if (r.complete) return "✺ Full recipe";
 if (r.photos && r.photos.length && !(r.sections||[]).length) return "◎ Photo recipe";
 return "✳ Family notes";
}
function card(r) {
 const g=group(r), isSaved=saved.has(r.slug), photo=r.photos && r.photos[0], who=from(r);
 return '<article class="recipe-card"><div class="card-art '+g+(photo?" has-photo":"")+'"><span class="number">RECIPE '+String(r.number).padStart(3,"0")+'</span>'+
  '<span class="food-emoji" aria-hidden="true">'+emoji(r)+'</span>'+
  (photo?'<img class="card-photo" src="'+html(photo.thumb)+'" alt="" loading="lazy" decoding="async">':"")+
  '<button class="heart'+(isSaved?" saved":"")+'" type="button" data-save="'+html(r.slug)+'" aria-label="'+(isSaved?"Remove saved recipe":"Save recipe")+'">'+(isSaved?"♥":"♡")+'</button></div>'+
  '<div class="card-body"><div class="card-meta"><span class="type '+g+'">'+html(label(r))+'</span>'+(who?'<span class="time">From '+html(who)+'</span>':"")+'</div>'+
  '<h3>'+html(r.title)+'</h3><p>'+html(r.summary)+'</p><div class="card-footer"><small>'+status(r)+'</small>'+
  '<button type="button" data-open="'+html(r.slug)+'" class="open-recipe">View recipe <span>↗</span></button></div></div></article>';
}
function render() {
 let list=recipes.filter(matches);
 list.sort(sort==="old" ? (a,b)=>a.number-b.number : sort==="az" ? (a,b)=>a.title.localeCompare(b.title) : (a,b)=>b.number-a.number);
 $("#recipe-grid").innerHTML=list.slice(0,shown).map(card).join("");
 $("#result-count").textContent="Showing "+Math.min(shown,list.length)+" of "+list.length+" family recipes";
 $("#empty").hidden=list.length!==0; $("#more").hidden=shown>=list.length;
 $("#saved-total").textContent=saved.size;
 $("#show-saved").setAttribute("aria-pressed",String(savedOnly));
 $("#cook").value=cook; $("#kashrut").value=kashrut;
 document.querySelectorAll("#filters [data-filter]").forEach(btn=>{
  const isActive=btn.dataset.filter===type;
  btn.classList.toggle("active",isActive);
  btn.setAttribute("aria-pressed",String(isActive));
 });
 document.querySelectorAll("#cook-list [data-cook]").forEach(btn=>btn.classList.toggle("active",btn.dataset.cook===cook));
}
function save(slug) {
 if(saved.has(slug)) saved.delete(slug); else saved.add(slug);
 try {localStorage.setItem(storeKey,JSON.stringify([...saved]));} catch {}
 render();
 const btn=$("#modal-save");if(btn && active && active.slug===slug) btn.textContent=saved.has(slug)?"♥ Saved":"♡ Save recipe";
}
const sub = text => '<li class="sub-heading">'+html(text)+'</li>';
function ingredients(s) {
 return '<ul class="ingredient-list">'+s.items.map(i=>i.sub?sub(i.text):'<li><label><input type="checkbox"><span>'+linkify(i.text)+'</span></label></li>').join("")+'</ul>';
}
function steps(s) {
 let html_="", open=false;
 s.items.forEach(i=>{
  if(i.sub){ if(open) html_+="</ol>"; html_+='<p class="step-heading">'+html(i.text)+'</p>'; open=false; return; }
  if(!open){ html_+='<ol class="step-list">'; open=true; }
  html_+="<li><span>"+linkify(i.text)+"</span></li>";
 });
 return html_+(open?"</ol>":"");
}
function prose(s) {
 return s.items.map(i=>i.sub?'<h4>'+html(i.text)+'</h4>':'<p>'+linkify(i.text)+'</p>').join("");
}
function detail(r) {
 const date=r.published ? new Date(r.published+"T12:00:00").toLocaleDateString(undefined,{month:"long",year:"numeric"}) : "";
 const info=[
  ...(r.facts||[]).map(f=>"◷ "+f),
  COURSES[r.courses[0]],
  r.gluten_free ? "Gluten free" : null,
  r.shabbat ? "✳ Shabbat" : null,
  r.pesach ? "✳ Pesach" : r.holiday ? "✳ Chagim" : null,
  date ? "Shared "+date : null
 ].filter(Boolean).map(s=>"<span>"+html(s)+"</span>").join("");
 const intro=section(r,"intro"), notes=section(r,"notes"), tools=section(r,"tools"), ing=section(r,"ingredients"), dir=section(r,"directions"), method=section(r,"method");
 let content="";
 if (r.in_progress) content+='<div class="archive-warning"><h3>Still being written up</h3><p>This one was saved on the blog as a work in progress, so some amounts or steps may be missing. Check the photos'+(r.source_url?' or the <a href="'+html(r.source_url)+'" target="_blank" rel="noopener noreferrer">original post</a>':"")+'.</p></div>';
 if (intro) content+='<div class="detail-prose">'+prose(intro)+'</div>';
 if (notes) content+='<div class="detail-note"><h3>Notes from the kitchen</h3>'+prose(notes)+'</div>';
 if (tools) content+='<div class="detail-note tools"><h3>You’ll need</h3><ul>'+tools.items.map(i=>i.sub?'<li class="sub-heading">'+html(i.text)+'</li>':'<li>'+linkify(i.text)+'</li>').join("")+'</ul></div>';
 if (ing || dir) {
  content+='<div class="detail-columns'+(ing&&dir?"":" single")+'">'+(ing?'<div><h3>Ingredients</h3>'+ingredients(ing)+'</div>':"")+(dir?'<div><h3>Let’s cook</h3>'+steps(dir)+'</div>':"")+'</div>';
 }
 if (method) content+='<div class="detail-columns single"><div><h3>How it’s made</h3><div class="detail-prose">'+prose(method)+'</div></div></div>';
 if (!(r.sections||[]).length && !(r.photos||[]).length) content+='<div class="archive-warning"><p>This post doesn’t have the recipe written out yet.</p></div>';
 // Finished recipes lead with a dish photo; posts that are mostly photos (often of handwritten recipe
 // cards) show every picture full width and uncropped so they stay readable.
 const photoRecipe=!r.complete || r.in_progress, lead=!photoRecipe && r.photos && r.photos[0], album=(r.photos||[]).slice(lead?1:0);
 if (album.length) {
  content+='<div class="gallery-block"><h3>'+(photoRecipe?"The recipe, in photos":"From the family album")+'</h3><div class="gallery'+(photoRecipe?" full":album.length===1?" one":"")+'">'+
   album.map(p=>'<figure><a href="'+html(p.src)+'" target="_blank" rel="noopener noreferrer"><img src="'+html(p.thumb)+'"'+(photoRecipe?srcset(p):"")+' alt="'+html(p.caption||r.title)+'" loading="lazy"></a>'+(p.caption?'<figcaption>'+html(p.caption)+'</figcaption>':"")+'</figure>').join("")+'</div></div>';
 }
 const credits=[r.adapted_from?'Adapted from '+linkify(r.adapted_from):null, r.source_url?'<a href="'+html(r.source_url)+'" target="_blank" rel="noopener noreferrer">View the original blog post ↗</a>':null].filter(Boolean).join(" · ");
 const who=r.cooks && r.cooks.length ? " · FROM "+r.cooks.join(" & ").toUpperCase() : "";
 $("#modal-content").innerHTML='<article class="detail"><p class="eyebrow">RECIPE '+String(r.number).padStart(3,"0")+' · '+html(label(r).toUpperCase())+html(who)+'</p>'+
  '<h2 id="modal-title">'+html(r.title)+'</h2><p>'+html(r.summary)+'</p><div class="detail-info">'+info+'</div>'+
  (lead?'<figure class="detail-photo"><img src="'+html(lead.thumb)+'"'+srcset(lead)+' alt="'+html(lead.caption||r.title)+'">'+(lead.caption?'<figcaption>'+html(lead.caption)+'</figcaption>':"")+'</figure>':"")+content+
  (credits?'<p class="detail-credits">'+credits+'</p>':"")+
  '<div class="detail-actions"><button id="modal-save" data-save="'+html(r.slug)+'" class="button primary" type="button">'+(saved.has(r.slug)?"♥ Saved":"♡ Save recipe")+
  '</button><button class="button outlined" id="detail-print" type="button">Print recipe ⎙</button></div></article>';
}
function openRecipe(slug,writeUrl=true) {
 const r=recipes.find(item=>item.slug===slug);
 if(!r)return;
 active=r;priorFocus=document.activeElement;detail(r);
 $("#modal").hidden=false;document.body.style.overflow="hidden";
 $(".modal-window").scrollTop=0;
 document.title=r.title+" — AshkeSephard";
 if(writeUrl){const url=new URL(location.href);url.searchParams.set("recipe",slug);history.pushState({recipe:slug},"",url);}
 const close=document.querySelector('.modal-header [data-close]');if(close)close.focus();
}
function closeRecipe(writeUrl=true) {
 $("#modal").hidden=true;document.body.style.overflow="";active=null;
 document.title="AshkeSephard — family recipes, passed down";
 if(writeUrl){const url=new URL(location.href);url.searchParams.delete("recipe");history.replaceState({},"",url);}
 if(priorFocus && document.contains(priorFocus))priorFocus.focus();
}
function fromUrl() {
 const slug=new URLSearchParams(location.search).get("recipe");
 if(slug)openRecipe(slug,false);else if(!$("#modal").hidden)closeRecipe(false);
}
function cooksSection() {
 const counts=new Map();
 recipes.forEach(r=>(r.cooks||[]).forEach(c=>counts.set(c,(counts.get(c)||0)+1)));
 const ordered=[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
 $("#cook").insertAdjacentHTML("beforeend",ordered.map(([c,n])=>'<option value="'+html(c)+'">'+html(c)+' ('+n+')</option>').join(""));
 $("#cook-list").innerHTML=ordered.map(([c,n])=>'<button type="button" class="cook" data-cook="'+html(c)+'"><span class="cook-initial" aria-hidden="true">'+html(c[0])+'</span><span><strong>'+html(c)+'</strong><small>'+n+' recipe'+(n===1?"":"s")+'</small></span></button>').join("");
 $("#stat-cooks").textContent=counts.size;
}
let toastTimer=null;
function notify(message){const n=$("#toast");n.textContent=message;n.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>n.hidden=true,2300);}
function resetPaging(){shown=12;}
document.addEventListener("click",e=>{
 const saveButton=e.target.closest("[data-save]");
 if(saveButton){save(saveButton.dataset.save);return;}
 const open=e.target.closest("[data-open]");
 if(open){openRecipe(open.dataset.open);return;}
 const cookButton=e.target.closest("[data-cook]");
 if(cookButton){cook=cook===cookButton.dataset.cook?"":cookButton.dataset.cook;resetPaging();render();$("#recipes").scrollIntoView({behavior:"smooth"});return;}
 const close=e.target.closest("[data-close]");
 if(close && !$("#modal").hidden){closeRecipe();return;}
 if(e.target.closest("#print") || e.target.closest("#detail-print"))window.print();
});
document.addEventListener("error",e=>{
 const img=e.target;
 if(img.tagName!=="IMG")return;
 if(img.classList.contains("card-photo")){img.closest(".card-art").classList.remove("has-photo");img.remove();}
 else{const fig=img.closest("figure");if(fig)fig.remove();}
},true);
$("#search").addEventListener("input",e=>{search=e.target.value.trim().toLowerCase();resetPaging();render();});
$("#filters").addEventListener("click",e=>{const b=e.target.closest("[data-filter]");if(b){type=b.dataset.filter;resetPaging();render();}});
$("#sort").addEventListener("change",e=>{sort=e.target.value;resetPaging();render();});
$("#cook").addEventListener("change",e=>{cook=e.target.value;resetPaging();render();});
$("#kashrut").addEventListener("change",e=>{kashrut=e.target.value;resetPaging();render();});
$("#show-saved").addEventListener("click",()=>{savedOnly=!savedOnly;resetPaging();render();});
$("#more").addEventListener("click",()=>{shown+=12;render();});
$("#clear").addEventListener("click",()=>{search="";type="all";cook="";kashrut="";savedOnly=false;resetPaging();$("#search").value="";render();});
$("#surprise-button").addEventListener("click",()=>{let full=recipes.filter(r=>r.complete&&!r.in_progress);if(!full.length)full=recipes;if(full.length)openRecipe(full[Math.floor(Math.random()*full.length)].slug);});
$("#copy").addEventListener("click",async()=>{if(!active)return;try{await navigator.clipboard.writeText(location.href);notify("Recipe link copied!");}catch{notify("Copy the page URL to share this recipe.");}});
document.addEventListener("keydown",e=>{
 if(e.key==="Escape" && !$("#modal").hidden)closeRecipe();
 if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==="k"){e.preventDefault();$("#search").focus();}
});
window.addEventListener("popstate",fromUrl);
async function init(){
 try{
  const response=await fetch("./data/recipes.json",{cache:"no-cache"});
  if(!response.ok)throw Error("Could not load recipes: "+response.status);
  const data=await response.json();
  if(!Array.isArray(data.recipes))throw Error("Unexpected recipe format");
  recipes=data.recipes.filter(r=>typeof r.number==="number"&&typeof r.slug==="string"&&typeof r.title==="string");
  recipes.forEach(r=>{r.courses=Array.isArray(r.courses)&&r.courses.length?r.courses:["mains"];searchIndex.set(r.slug,indexText(r));});
  $("#stat-recipes").textContent=recipes.length;
  $("#stat-shabbat").textContent=recipes.filter(r=>r.shabbat||r.holiday).length;
  cooksSection();
  render();fromUrl();
 }catch(err){
  console.error(err);
  $("#result-count").textContent="Recipe collection unavailable";
  $("#recipe-grid").innerHTML='<div class="archive-warning"><h3>Could not load recipes</h3><p>Please refresh the page in a moment.</p></div>';
 }
}
init();
})();
