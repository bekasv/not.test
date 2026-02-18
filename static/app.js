(function(){
  // timer
  const timer = document.querySelector(".timer");
  if (timer){
    let rem = parseInt(timer.dataset.remaining || "0", 10);
    const mmss = timer.querySelector(".mmss");

    const tick = () => {
      const m = Math.floor(rem/60), s = rem%60;
      mmss.textContent = `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
      if (rem <= 0){
        // авто-завершение
        const finishBtn = document.querySelector('button[formaction$="/finish"]');
        if (finishBtn) finishBtn.click();
        return;
      }
      rem -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  }

  // enable confirm button on selection
  const confirmBtn = document.getElementById("confirmBtn");
  const form = document.getElementById("answerForm");
  if (confirmBtn && form){
    const inputs = form.querySelectorAll('input[type="radio"], input[type="checkbox"]');
    const update = () => {
      let any = false;
      inputs.forEach(i => { if (i.checked) any = true; });
      confirmBtn.disabled = !any;
    };
    inputs.forEach(i => i.addEventListener("change", update));
    update();
  }
})();
