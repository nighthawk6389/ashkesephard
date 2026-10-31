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
 if (/"(?:chicken|shrimp)"/.test(t)) return "🥡";
 if (/noodles|spaghetti|macaroni|gnocchi|pasta/.test(t) && !/kugel|pudding/.test(t)) return "🍝";
 if (/dressing|sauce\)?$|mayonnaise|\brub\b|spice|charoset|marror|chutney|relish/.test(t)) return "🫙";
 if (/eggplant|babaganoush/.test(t)) return "🍆";
 if (/soup|chamin|chulent|chollent|stew|chili|chowder/.test(t)) return "🍲";
 if (/meatball|meatloaf|patties|burger|stuffed (?:cabbage|peppers)/.test(t)) return "🥘";
 if (/chicken|schnitzel|hens|wings|duck/.test(t)) return "🍗";
 if (/salad|slaw|matbucha|tznon|bishbash/.test(t)) return "🥗";
 if (/\bcake|tiramisu|quiche|cheesecake/.test(t)) return "🍰";
 if (/cookie|mandelbroit|bars|squares|hamatashen|doughnut|cream puff|balls|popcorn/.test(t)) return "🍪";
 if (/pie|muffin|pear/.test(t)) return "🥧";
 if (/kugel|pashtida|casserole|ziti|lasagna/.test(t)) return "🥘";
 if (/latke|pancake|blintz|french toast|toast|\beggs?\b|shakshouka/.test(t)) return "🍳";
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
const BOT_EMAIL = ((window.ASHKE_CONFIG || {}).recipesEmail || "").trim();
const VERDICTS = {"as_is":"✓ Perfect as is","changes":"✎ Made some changes","didnt_work":"✗ Didn’t work out"};
const shortDate = iso => iso ? new Date(iso+"T12:00:00").toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}) : "";
const recipeUrl = r => location.origin+location.pathname+"?recipe="+encodeURIComponent(r.slug);
const storeKey = "ashkesephard-saved";
let saved;
try { saved = new Set(JSON.parse(localStorage.getItem(storeKey) || "[]")); } catch { saved = new Set(); }
let comments=[], requests=[];
const commentsBySlug = new Map();
const tried = r => (commentsBySlug.get(r.slug)||[]).filter(c=>c.made_it).length;
let recipes=[], type="all", search="", sort="new", cook="", kashrut="", savedOnly=false, shown=12, active=null, priorFocus=null;
const searchIndex = new Map();
function indexText(r) {
 return [r.title,r.summary,(r.cooks||[]).join(" "),(r.labels||[]).join(" "),COURSES[r.courses[0]]||"",label(r),
  ...(r.sections||[]).flatMap(s=>s.items.map(i=>i.text)),...(r.photos||[]).map(p=>p.caption||""),
  ...(commentsBySlug.get(r.slug)||[]).map(c=>c.name+" "+c.text+" "+c.changes),r.added_by||""].join(" ").toLowerCase();
}
function matches(r) {
 if (type==="shabbat" ? !r.shabbat : type==="holiday" ? !r.holiday : type==="gf" ? !r.gluten_free : type==="tried" ? !tried(r) : type!=="all" && !r.courses.includes(type)) return false;
 if (cook && !(r.cooks||[]).includes(cook)) return false;
 if (kashrut && group(r)!==kashrut) return false;
 if (savedOnly && !saved.has(r.slug)) return false;
 return !search || search.split(/\s+/).every(word=>searchIndex.get(r.slug).includes(word));
}
function status(r) {
 if (r.in_progress) return "◌ Work in progress";
 if (tried(r)) return "♨ Tried by "+tried(r);
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
  '<h3 title="'+html(r.title)+'">'+html(r.title)+'</h3><p>'+html(r.summary)+'</p><div class="card-footer"><small>'+status(r)+'</small>'+
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
function photoGrid(photos, alt) {
 return '<div class="gallery'+(photos.length===1?" one":"")+'">'+photos.map(p=>'<figure><a href="'+html(p.src)+'" target="_blank" rel="noopener noreferrer"><img src="'+html(p.thumb)+'" alt="'+html(p.caption||alt)+'" loading="lazy"></a>'+(p.caption?'<figcaption>'+html(p.caption)+'</figcaption>':"")+'</figure>').join("")+'</div>';
}
function familySection(r) {
 const list=(commentsBySlug.get(r.slug)||[]).slice().sort((a,b)=>b.date.localeCompare(a.date));
 const intro=list.length ? "" : '<p class="family-empty">Nobody has posted about this one yet. Made it? Tell the family how it came out, and send a picture.</p>';
 return '<section class="family-block"><div class="family-head"><h3>From the family’s kitchens</h3>'+(tried(r)?'<span>Tried by '+tried(r)+'</span>':"")+'</div>'+intro+
  list.map(c=>'<article class="family-comment"><div class="family-meta"><span class="cook-initial" aria-hidden="true">'+html((c.name||"?")[0])+'</span><div><strong>'+html(c.name)+'</strong><small>'+html(shortDate(c.date))+'</small></div>'+
   (VERDICTS[c.verdict]?'<span class="verdict '+html(c.verdict)+'">'+html(VERDICTS[c.verdict])+'</span>':c.made_it?'<span class="verdict">Made it</span>':"")+'</div>'+
   (c.text?'<p>'+linkify(c.text)+'</p>':"")+(c.changes?'<p class="family-changes"><strong>What they changed:</strong> '+linkify(c.changes)+'</p>':"")+
   (c.photos&&c.photos.length?photoGrid(c.photos,"What "+c.name+" made"):"")+'</article>').join("")+
  '<div class="family-actions"><button type="button" class="button primary" data-mail="made" data-slug="'+html(r.slug)+'">♨ I made this ↗</button><button type="button" class="button outlined" data-mail="fix" data-slug="'+html(r.slug)+'">Suggest a fix ↗</button></div></section>';
}
function detail(r) {
 const date=r.published ? new Date(r.published+"T12:00:00").toLocaleDateString(undefined,{month:"long",year:"numeric"}) : "";
 const info=[
  ...(r.facts||[]).map(f=>"◷ "+f),
  COURSES[r.courses[0]],
  r.gluten_free ? "Gluten free" : null,
  r.shabbat ? "✳ Shabbat" : null,
  r.pesach ? "✳ Pesach" : r.holiday ? "✳ Chagim" : null,
  date ? "Shared "+date : null,
  r.added_by && r.source==="email" ? "Added by "+r.added_by : null
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
 // Summaries are often the first line of the notes; don't print the same sentence twice.
 const firstNote=[intro,notes].map(s=>s&&s.items.find(i=>!i.sub)).find(Boolean);
 const repeatsNote=!!firstNote && firstNote.text.replace(/^(?:notes?|ema says|savta says)\s*[:\-–]\s*/i,"").startsWith(r.summary.replace(/[.…]$/,""));
 const who=r.cooks && r.cooks.length ? " · FROM "+r.cooks.join(" & ").toUpperCase() : "";
 $("#modal-content").innerHTML='<article class="detail"><p class="eyebrow">RECIPE '+String(r.number).padStart(3,"0")+' · '+html(label(r).toUpperCase())+html(who)+'</p>'+
  '<h2 id="modal-title">'+html(r.title)+'</h2>'+(repeatsNote?"":'<p>'+html(r.summary)+'</p>')+'<div class="detail-info">'+info+'</div>'+
  (lead?'<figure class="detail-photo"><img src="'+html(lead.thumb)+'"'+srcset(lead)+' alt="'+html(lead.caption||r.title)+'">'+(lead.caption?'<figcaption>'+html(lead.caption)+'</figcaption>':"")+'</figure>':"")+content+
  familySection(r)+(credits?'<p class="detail-credits">'+credits+'</p>':"")+
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
 $("#cook-names").innerHTML=ordered.map(([c])=>'<option value="'+html(c)+'">').join("");
}
function renderTried() {
 const latest=comments.slice().sort((a,b)=>b.date.localeCompare(a.date)).filter(c=>recipes.some(r=>r.slug===c.recipe)).slice(0,6);
 $("#tried").hidden=!latest.length;
 $("#tried-list").innerHTML=latest.map(c=>{
  const r=recipes.find(x=>x.slug===c.recipe), photo=c.photos&&c.photos[0];
  return '<button type="button" class="tried-card" data-open="'+html(r.slug)+'"><span class="tried-art card-art '+group(r)+(photo?" has-photo":"")+'">'+(photo?'<img class="card-photo" src="'+html(photo.thumb)+'" alt="" loading="lazy">':'<span class="food-emoji" aria-hidden="true">'+emoji(r)+'</span>')+'</span>'+
   '<span class="tried-body"><small>'+html(c.name)+(c.made_it?" made":" commented")+' · '+html(shortDate(c.date))+'</small><strong>'+html(r.title)+'</strong>'+
   (VERDICTS[c.verdict]?'<span class="verdict '+html(c.verdict)+'">'+html(VERDICTS[c.verdict])+'</span>':"")+(c.text?'<span class="tried-quote">“'+html(c.text)+'”</span>':"")+'</span></button>';
 }).join("");
}
function renderRequests() {
 const open=requests.filter(q=>q.status==="open").sort((a,b)=>b.date.localeCompare(a.date));
 const found=requests.filter(q=>q.status==="found"&&recipes.some(r=>r.slug===q.recipe)).sort((a,b)=>(b.found||b.date).localeCompare(a.found||a.date)).slice(0,6);
 if(!open.length && !found.length){$("#request-list").innerHTML='<div class="empty request-empty"><div>📜</div><h3>No requests yet</h3><p>Looking for a recipe nobody has written down? Ask the family.</p></div>';return;}
 $("#request-list").innerHTML=open.map(q=>'<article class="request-card"><span class="request-status">Looking for</span><h3>'+html(q.title)+'</h3>'+(q.details?'<p>'+html(q.details)+'</p>':"")+
  '<div class="request-foot"><small>Asked by '+html(q.name)+' · '+html(shortDate(q.date))+'</small><button type="button" class="open-recipe" data-mail="have" data-request="'+html(q.id)+'">I have this one <span>↗</span></button></div></article>').join("")+
  found.map(q=>{const r=recipes.find(x=>x.slug===q.recipe);return '<article class="request-card found"><span class="request-status">✓ Found</span><h3>'+html(q.title)+'</h3><p>Asked by '+html(q.name)+'. Now on the site as “'+html(r.title)+'”.</p>'+
   '<div class="request-foot"><small>'+html(shortDate(q.found||q.date))+'</small><button type="button" class="open-recipe" data-open="'+html(r.slug)+'">View recipe <span>↗</span></button></div></article>';}).join("");
}
function sendMail(subject, body) {
 if(!BOT_EMAIL){notify("The recipe inbox isn’t set up yet. Check back soon!");return false;}
 const link=document.createElement("a");
 link.href="mailto:"+BOT_EMAIL+"?subject="+encodeURIComponent(subject)+"&body="+encodeURIComponent(body);
 link.hidden=true;document.body.appendChild(link);link.click();link.remove();
 return true;
}
function mailTemplate(button) {
 const r=recipes.find(x=>x.slug===button.dataset.slug), q=requests.find(x=>x.id===button.dataset.request);
 switch(button.dataset.mail){
  case "made": return ["Made it: "+r.title, "Recipe: "+recipeUrl(r)+"\n\nHow did it come out? Perfect as is, or did you change something?\n\n\n(Attach photos of what you made!)\n"];
  case "fix": return ["Fix: "+r.title, "Recipe: "+recipeUrl(r)+"\n\nWhat should be changed?\n\n"];
  case "request": return ["Request: ", "Which recipe are you looking for? Whose was it, and what do you remember about it?\n\n"];
  case "have": return ["New recipe: "+q.title, "This is for the request “"+q.title+"” ("+q.id+").\n\nAttach a photo of the recipe, or type it here:\n\n"];
  case "photo": return ["New recipe: ", "Attached is a photo of the recipe (and the dish, if I have one).\nWhose recipe is it? \n\n"];
 }
}
let toastTimer=null;
function notify(message){const n=$("#toast");n.textContent=message;n.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>n.hidden=true,2300);}
function resetPaging(){shown=12;}
document.addEventListener("click",e=>{
 const mailButton=e.target.closest("[data-mail]");
 if(mailButton){const t=mailTemplate(mailButton);if(t)sendMail(t[0],t[1]);return;}
 if(e.target.closest("[data-filter-tried]")){type="tried";resetPaging();render();$("#recipes").scrollIntoView({behavior:"smooth"});return;}
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
 if(e.key==="Escape" && !$("#modal").hidden && $("#wizard").hidden)closeRecipe();
 if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==="k"){e.preventDefault();$("#search").focus();}
});
window.addEventListener("popstate",fromUrl);

// ---- Add-a-recipe wizard: builds an email for the recipe bot (no accounts, nothing stored server-side)
const wizardKey="ashkesephard-wizard", wform=$("#wizard-form"), WIZARD_STEPS=4;
let wizardStep=1, wizardFocus=null;
const lines=text=>String(text||"").split("\n").map(l=>l.trim()).filter(Boolean);
function wizardData(){
 const f=new FormData(wform), get=k=>String(f.get(k)||"").trim();
 return {title:get("title"),whose:get("whose"),course:get("course"),kitchen:get("kitchen"),tags:f.getAll("tags"),ingredients:get("ingredients"),steps:get("steps"),notes:get("notes")};
}
function wizardText(d){
 const out=["Recipe: "+d.title];
 if(d.whose)out.push("Whose recipe: "+d.whose);
 const kind=[d.course,d.kitchen,...d.tags].filter(Boolean).join(" · ");
 if(kind)out.push("Kind of dish: "+kind);
 out.push("","Ingredients:",...lines(d.ingredients).map(l=>/:$/.test(l)?l:"- "+l.replace(/^[-•*]\s*/,"")));
 let n=0;
 out.push("","Directions:",...lines(d.steps).map(l=>/:$/.test(l)?l:(++n)+". "+l.replace(/^\d+[.)]\s*/,"")));
 if(d.notes)out.push("","Notes:",d.notes);
 out.push("","(Photos attached: the dish and/or the recipe card)");
 return out.join("\n")+"\n";
}
function wizardPreview(d){
 const kind=[d.course,d.kitchen,...d.tags,d.whose?"From "+d.whose:""].filter(Boolean).map(t=>"<span>"+html(t)+"</span>").join("");
 const ing=lines(d.ingredients), st=lines(d.steps);
 return '<h3>'+html(d.title||"Untitled recipe")+'</h3>'+(kind?'<div class="detail-info">'+kind+'</div>':"")+
  '<div class="detail-columns"><div><h4>Ingredients</h4>'+(ing.length?'<ul class="ingredient-list">'+ing.map(l=>/:$/.test(l)?sub(l.replace(/:$/,"")):'<li><span>'+html(l.replace(/^[-•*]\s*/,""))+'</span></li>').join("")+'</ul>':'<p class="field-hint">No ingredients yet. A photo of the recipe works too.</p>')+'</div>'+
  '<div><h4>Steps</h4>'+(st.length?'<ol class="step-list">'+st.filter(l=>!/:$/.test(l)).map(l=>'<li><span>'+html(l.replace(/^\d+[.)]\s*/,""))+'</span></li>').join("")+'</ol>':'<p class="field-hint">No steps yet.</p>')+'</div></div>'+
  (d.notes?'<div class="detail-note"><h3>Notes</h3><p>'+html(d.notes)+'</p></div>':"");
}
function saveDraft(){try{localStorage.setItem(wizardKey,JSON.stringify({...wizardData(),step:wizardStep}));}catch{}}
function loadDraft(){
 let d;try{d=JSON.parse(localStorage.getItem(wizardKey)||"null");}catch{d=null;}
 if(!d)return;
 ["title","whose","course","kitchen","ingredients","steps","notes"].forEach(k=>{if(wform.elements[k]&&d[k])wform.elements[k].value=d[k];});
 wform.querySelectorAll('[name="tags"]').forEach(box=>box.checked=(d.tags||[]).includes(box.value));
}
function showStep(step){
 wizardStep=step;
 wform.querySelectorAll(".wizard-step").forEach(fs=>fs.hidden=Number(fs.dataset.step)!==step);
 wform.querySelectorAll(".wizard-progress span").forEach((dot,i)=>dot.classList.toggle("done",i<step));
 $("#wizard-step-label").textContent="STEP "+step+" OF "+WIZARD_STEPS;
 $("#wizard-back").hidden=step===1;
 $("#wizard-next").hidden=step===WIZARD_STEPS;
 $("#wizard-send").hidden=$("#wizard-copy").hidden=step!==WIZARD_STEPS;
 if(step===WIZARD_STEPS){
  $("#wizard-preview").innerHTML=wizardPreview(wizardData());
  $("#wizard-send-note").textContent=BOT_EMAIL?"If your email app doesn’t open, use Copy recipe and paste it into an email to "+BOT_EMAIL+".":"The recipe inbox isn’t set up yet, so for now use Copy recipe.";
 }
 $("#wizard .modal-window").scrollTop=0;
 const first=wform.querySelector('.wizard-step:not([hidden]) input, .wizard-step:not([hidden]) textarea');
 if(first)first.focus({preventScroll:true});
}
function openWizard(){
 wizardFocus=document.activeElement;loadDraft();
 $("#wizard").hidden=false;document.body.style.overflow="hidden";showStep(1);
}
function closeWizard(){
 $("#wizard").hidden=true;if($("#modal").hidden)document.body.style.overflow="";
 if(wizardFocus&&document.contains(wizardFocus))wizardFocus.focus();
}
document.addEventListener("click",e=>{
 if(e.target.closest("[data-wizard]")){e.preventDefault();openWizard();}
 else if(e.target.closest("[data-wizard-close]"))closeWizard();
});
wform.addEventListener("input",saveDraft);
wform.addEventListener("submit",e=>e.preventDefault());
$("#wizard-back").addEventListener("click",()=>showStep(Math.max(1,wizardStep-1)));
$("#wizard-next").addEventListener("click",()=>{
 if(wizardStep===1&&!wizardData().title){wform.elements.title.focus();notify("Give the recipe a name first.");return;}
 saveDraft();showStep(Math.min(WIZARD_STEPS,wizardStep+1));
});
$("#wizard-send").addEventListener("click",()=>{
 const d=wizardData();
 if(sendMail("New recipe: "+d.title,wizardText(d))){try{localStorage.removeItem(wizardKey);}catch{}}
});
$("#wizard-copy").addEventListener("click",async()=>{
 const d=wizardData();
 try{await navigator.clipboard.writeText("Subject: New recipe: "+d.title+"\n\n"+wizardText(d));notify("Recipe copied. Paste it into an email.");}
 catch{notify("Couldn’t copy. Select the preview text instead.");}
});
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&!$("#wizard").hidden)closeWizard();});
async function init(){
 try{
  const [response,community]=await Promise.all([fetch("./data/recipes.json",{cache:"no-cache"}),
   fetch("./data/community.json",{cache:"no-cache"}).then(r=>r.ok?r.json():{}).catch(()=>({}))]);
  comments=Array.isArray(community.comments)?community.comments:[];
  requests=Array.isArray(community.requests)?community.requests:[];
  comments.forEach(c=>{if(!commentsBySlug.has(c.recipe))commentsBySlug.set(c.recipe,[]);commentsBySlug.get(c.recipe).push(c);});
  if(!response.ok)throw Error("Could not load recipes: "+response.status);
  const data=await response.json();
  if(!Array.isArray(data.recipes))throw Error("Unexpected recipe format");
  recipes=data.recipes.filter(r=>typeof r.number==="number"&&typeof r.slug==="string"&&typeof r.title==="string");
  recipes.forEach(r=>{r.courses=Array.isArray(r.courses)&&r.courses.length?r.courses:["mains"];searchIndex.set(r.slug,indexText(r));});
  $("#stat-recipes").textContent=recipes.length;
  $("#stat-shabbat").textContent=recipes.filter(r=>r.shabbat||r.holiday).length;
  cooksSection();renderTried();renderRequests();
  render();fromUrl();
 }catch(err){
  console.error(err);
  $("#result-count").textContent="Recipe collection unavailable";
  $("#recipe-grid").innerHTML='<div class="archive-warning"><h3>Could not load recipes</h3><p>Please refresh the page in a moment.</p></div>';
 }
}
init();
})();
