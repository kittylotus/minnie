// Run in the head so recovery mode never loads the override stylesheet.
window.minnieDefaultTheme=new URLSearchParams(location.search).get('theme')==='default';
if(!window.minnieDefaultTheme){
  const link=document.createElement('link');
  link.id='custom-theme';link.rel='stylesheet';link.href='/custom.css';
  document.head.append(link);
}
