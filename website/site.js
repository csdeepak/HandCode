// A copy button on each code block. docs/0054.
document.querySelectorAll("pre").forEach(function (pre) {
  var button = document.createElement("button");
  button.className = "copy";
  button.type = "button";
  button.textContent = "Copy";
  button.addEventListener("click", function () {
    var code = pre.querySelector("code") || pre;
    navigator.clipboard.writeText(code.innerText).then(function () {
      button.textContent = "Copied";
      setTimeout(function () { button.textContent = "Copy"; }, 1500);
    }, function () {
      button.textContent = "Select and copy";
    });
  });
  pre.appendChild(button);
});
