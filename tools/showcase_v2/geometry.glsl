// Authored two-dimensional geometry for the 120-second transformation film.
// Requires PI, TAU, CYAN, GOLD, PINK, WHITE and rot/lineDistance/glow helpers.
// Every main shape change below interpolates geometry, not completed pictures.

float geoGate(float t, float start, float finish) {
    return smoothstep(start,start+0.65,t)*(1.0-smoothstep(finish-0.65,finish,t));
}
float geoStroke(float distanceToLine,float width,float aa) {
    return 1.0-smoothstep(width,width+aa,distanceToLine);
}
float geoHash(float value) { return fract(sin(value*37.713+7.19)*43758.5453); }
float geoRayCrossing(vec2 p,vec2 a,vec2 b) {
    if((a.y>p.y)!=(b.y>p.y)) {
        float crossing=a.x+(p.y-a.y)*(b.x-a.x)/(b.y-a.y);
        return step(p.x,crossing);
    }
    return 0.0;
}

vec2 geoPolygon(float u,float sides,float radius,float offset) {
    float slot=u*sides;
    float a=floor(slot)*TAU/sides+offset;
    float b=a+TAU/sides;
    return mix(vec2(cos(a),sin(a)),vec2(cos(b),sin(b)),fract(slot))*radius;
}

vec2 geoShape(float u,float kind) {
    float a=u*TAU+PI*0.5;
    if(kind<0.5) return vec2(cos(a),sin(a))*2.35;
    if(kind<1.5) return geoPolygon(u,4.0,2.65,PI*0.25);
    if(kind<2.5) return geoPolygon(u,3.0,2.55,PI*0.5);
    if(kind<3.5) return geoPolygon(u,6.0,2.4,PI/6.0);
    if(kind<4.5) {
        float slot=u*10.0;
        float n=floor(slot), a=n*PI/5.0+PI*0.5, b=a+PI/5.0;
        float ra=mix(2.55,1.04,mod(n,2.0));
        float rb=mix(1.04,2.55,mod(n,2.0));
        return mix(vec2(cos(a),sin(a))*ra,vec2(cos(b),sin(b))*rb,fract(slot));
    }
    if(kind<5.5) return vec2(cos(a),sin(a))*(1.95+0.48*cos(6.0*a));
    return vec2(2.45*sin(a*2.0),2.12*sin(a*3.0));
}

vec2 geoMorphPoint(float u,float evolution,float angle) {
    float stepIndex=min(5.0,floor(evolution));
    float blend=smoothstep(0.12,0.86,evolution-stepIndex);
    return rot(angle)*mix(geoShape(u,stepIndex),geoShape(u,stepIndex+1.0),blend);
}

vec3 geoMorphChain(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float progress=clamp((t-12.0)/2.38,0.0,6.0);
    float angle=0.07*(t-12.0)+0.08*sin((t-12.0)*0.6);
    vec2 q=p-vec2(0.0,-0.12);
    float mainDistance=100.0, echoDistance=100.0, innerDistance=100.0, crossings=0.0;
    vec2 previous=geoMorphPoint(0.0,progress,angle);
    vec2 echoPrevious=geoMorphPoint(0.0,max(0.0,progress-0.19),angle-0.055)*1.08;
    vec2 innerPrevious=geoMorphPoint(0.0,min(6.0,progress+0.15),angle+0.055)*0.89;
    for(int j=1;j<=96;j++) {
        float u=float(j)/96.0;
        vec2 current=geoMorphPoint(u,progress,angle);
        vec2 echoCurrent=geoMorphPoint(u,max(0.0,progress-0.19),angle-0.055)*1.08;
        vec2 innerCurrent=geoMorphPoint(u,min(6.0,progress+0.15),angle+0.055)*0.89;
        mainDistance=min(mainDistance,lineDistance(q,previous,current));
        echoDistance=min(echoDistance,lineDistance(q,echoPrevious,echoCurrent));
        innerDistance=min(innerDistance,lineDistance(q,innerPrevious,innerCurrent));
        crossings+=geoRayCrossing(q,previous,current);
        previous=current;
        echoPrevious=echoCurrent;
        innerPrevious=innerCurrent;
    }
    vec3 hue=mix(CYAN,PINK,0.5+0.5*sin(progress*0.9));
    float inside=mod(crossings,2.0);
    vec3 fillHue=mix(CYAN,PINK,0.5+0.4*sin(q.x*0.6+progress));
    float fillGradient=0.075+0.045*(0.5+0.5*sin(q.y*0.9-t*0.3));
    c+=fillHue*inside*fillGradient;
    c+=glow(echoDistance,0.009,GOLD,0.42,aa);
    c+=glow(innerDistance,0.006,CYAN,0.29,aa);
    c+=glow(mainDistance,0.024,hue,1.12,aa);
    c+=WHITE*geoStroke(mainDistance,0.005,aa)*0.68;
    c+=hue*exp(-dot(q,q)*0.35)*0.075;
    float drawU=fract((t-12.0)*0.23);
    vec2 cursor=geoMorphPoint(drawU,progress,angle);
    c+=glow(length(q-cursor),0.065,WHITE,1.15,aa);
    float reverseU=fract(0.5-(t-12.0)*0.19);
    vec2 reverseCursor=geoMorphPoint(reverseU,progress,angle);
    c+=glow(length(q-reverseCursor),0.055,GOLD,1.05,aa);
    for(int j=1;j<=8;j++) {
        float delay=float(j)*0.012;
        vec2 tail=geoMorphPoint(fract(drawU-delay),progress,angle);
        vec2 backTail=geoMorphPoint(fract(reverseU+delay),progress,angle);
        float fade=1.0-float(j)/9.0;
        c+=glow(length(q-tail),0.013+0.026*fade,CYAN,0.28*fade,aa);
        c+=glow(length(q-backTail),0.013+0.022*fade,GOLD,0.22*fade,aa);
    }
    // Corresponding vertices move with the body throughout each transform.
    for(int j=0;j<12;j++) {
        float u=float(j)/12.0;
        vec2 at=geoMorphPoint(u,progress,angle);
        c+=glow(length(q-at),0.029,GOLD,0.75,aa);
        float reveal=0.09+0.06*sin(t+float(j));
        c+=glow(lineDistance(q,at,vec2(0.0)),0.003,CYAN,reveal,aa);
    }
    // A perimeter dial frames the changing geometry without dominating it.
    float radius=length(q), a=atan(q.y,q.x);
    c+=glow(abs(radius-3.15),0.005,CYAN,0.22,aa);
    float tick=step(0.93,fract(a/TAU*72.0));
    c+=GOLD*geoStroke(abs(radius-3.32),0.05,aa)*tick*0.45;
    for(int j=0;j<6;j++) {
        float i=float(j), angle=i*TAU/6.0-t*0.12;
        vec2 center=vec2(cos(angle)*5.35,sin(angle)*2.85);
        vec2 local=(p-center)*4.0;
        float r=length(local);
        float petals=1.0+0.24*cos(atan(local.y,local.x)*(3.0+i));
        c+=glow(abs(r-petals)/4.0,0.006,mix(CYAN,GOLD,i/6.0),0.6,aa);
    }
    return c;
}

vec3 geoEuler(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float phase=(t-48.0)*1.2;
    float ellipse=0.5+0.5*sin((t-48.0)*0.45);
    float ax=mix(1.22,1.65,ellipse), ay=mix(1.65,1.0,ellipse);
    vec2 center=vec2(-3.85,-0.4);
    vec2 local=p-center;
    float ring=abs(length(local/vec2(ax,ay))-1.0)*min(ax,ay);
    c+=glow(ring,0.012,CYAN,0.8,aa);
    c+=glow(lineDistance(p,center-vec2(2.0,0.0),center+vec2(2.0,0.0)),0.005,CYAN,0.26,aa);
    c+=glow(lineDistance(p,center-vec2(0.0,2.0),center+vec2(0.0,2.0)),0.005,CYAN,0.26,aa);
    vec2 tip=center+vec2(ax*cos(phase),ay*sin(phase));
    c+=glow(lineDistance(p,center,tip),0.018,GOLD,1.0,aa);
    c+=glow(length(p-tip),0.052,WHITE,1.1,aa);
    vec2 waveStart=vec2(-1.2,tip.y);
    float dotted=step(0.38,fract(p.x*9.0));
    c+=glow(lineDistance(p,tip,waveStart),0.006,GOLD,0.35*dotted,aa);
    c+=glow(lineDistance(p,vec2(-1.2,-0.4),vec2(6.2,-0.4)),0.005,CYAN,0.3,aa);
    if(p.x>-1.2 && p.x<6.2) {
        float x=p.x+1.2;
        float a=phase-x*1.12;
        float y=-0.4+ay*sin(a);
        float dy=ay*1.12*cos(a);
        float distanceToWave=abs(p.y-y)/sqrt(1.0+dy*dy);
        c+=glow(distanceToWave,0.02,CYAN,1.05,aa);
        // The second projection peels away then rejoins the same oscillator.
        float split=smoothstep(52.0,55.0,t)*(1.0-smoothstep(62.0,65.0,t));
        float y2=-0.4+ax*cos(a);
        float d2=abs(p.y-y2)/sqrt(1.0+pow(ax*1.12*sin(a),2.0));
        c+=glow(d2,0.012,PINK,0.52*split,aa);
        float grid=abs(fract(x*0.5+0.5)-0.5);
        c+=CYAN*geoStroke(grid,0.001,aa*0.4)*0.055*
            smoothstep(-2.6,-2.4,p.y)*(1.0-smoothstep(1.4,1.6,p.y));
    }
    c+=glow(length(p-waveStart),0.04,GOLD,0.95,aa);
    // A quietly rotating coordinate square reinforces the changing basis.
    vec2 q=rot(-phase*0.17)*local;
    float box=max(abs(q.x)-1.8,abs(q.y)-1.8);
    c+=glow(abs(box),0.004,PINK,0.15,aa);
    return c;
}

float geoPolynomial(float x,float morph) {
    return mix(x*x*x,3.0*x*x,morph);
}
float geoPolynomialSlope(float x,float morph) {
    return mix(3.0*x*x,6.0*x,morph);
}
vec3 geoCalculus(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    vec2 origin=vec2(-1.0,-1.75);
    vec2 q=(p-origin)/vec2(2.0,0.75);
    float morph=smoothstep(66.8,70.9,t);
    float integral=smoothstep(71.8,76.7,t);
    float curve=100.0;
    vec2 previous=vec2(-2.0,geoPolynomial(-2.0,morph));
    for(int j=1;j<=80;j++) {
        float x=-2.0+float(j)*4.0/80.0;
        vec2 current=vec2(x,geoPolynomial(x,morph));
        curve=min(curve,lineDistance(p,origin+previous*vec2(2.0,0.75),origin+current*vec2(2.0,0.75)));
        previous=current;
    }
    float boundary=smoothstep(-3.6,-3.45,p.y)*(1.0-smoothstep(1.3,1.48,p.y));
    c+=glow(curve,0.019,mix(CYAN,PINK,morph),1.05,aa)*boundary;
    c+=glow(lineDistance(p,vec2(-5.3,origin.y),vec2(5.3,origin.y)),0.005,CYAN,0.32,aa);
    c+=glow(lineDistance(p,vec2(origin.x,-3.5),vec2(origin.x,1.1)),0.005,CYAN,0.32,aa);
    for(int j=-4;j<=5;j++) {
        float x=float(j);
        c+=glow(lineDistance(p,vec2(x,-1.82),vec2(x,-1.68)),0.004,GOLD,0.35,aa);
    }
    float cursorX=-1.1+2.2*(0.5+0.5*sin((t-66.0)*0.55));
    vec2 at=origin+vec2(cursorX,geoPolynomial(cursorX,morph))*vec2(2.0,0.75);
    float slope=geoPolynomialSlope(cursorX,morph)*0.375;
    vec2 tangent=normalize(vec2(1.0,slope))*1.35;
    c+=glow(lineDistance(p,at-tangent,at+tangent),0.012,GOLD,0.85*(1.0-integral),aa)*boundary;
    c+=glow(length(p-at),0.046,WHITE,1.0*(1.0-integral),aa)*boundary;
    if(integral>0.001 && q.x>=0.0 && q.x<=1.0 && q.y>=0.0) {
        float count=mix(5.0,40.0,smoothstep(77.0,82.5,t));
        float bin=floor(q.x*count);
        float x=(bin+0.5)/count;
        float barHeight=geoPolynomial(x,morph);
        float inside=1.0-smoothstep(barHeight,barHeight+aa/0.75,q.y);
        float margin=step(0.08,fract(q.x*count));
        c+=mix(CYAN,GOLD,bin/count)*inside*margin*integral*0.22;
        float upper=abs(q.y-barHeight)*0.75;
        c+=glow(upper,0.006,GOLD,0.55*integral,aa)*margin;
    }
    return c;
}

float geoHarmonic(float angle,float amount) {
    return sin(angle)+smoothstep(0.0,1.0,amount)*sin(3.0*angle)/3.0
        +smoothstep(1.0,2.0,amount)*sin(5.0*angle)/5.0
        +smoothstep(2.0,3.0,amount)*sin(7.0*angle)/7.0;
}
float geoHarmonicSlope(float angle,float amount) {
    return cos(angle)+smoothstep(0.0,1.0,amount)*cos(3.0*angle)
        +smoothstep(1.0,2.0,amount)*cos(5.0*angle)
        +smoothstep(2.0,3.0,amount)*cos(7.0*angle);
}
vec3 geoFourier(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float phase=(t-84.0)*1.6;
    float amount=smoothstep(84.8,88.7,t)+smoothstep(89.8,94.7,t)+smoothstep(95.8,99.7,t);
    vec2 tip=vec2(-4.1,-0.6);
    for(int j=0;j<4;j++) {
        float harmonic=2.0*float(j)+1.0;
        float weight=j==0?1.0:smoothstep(float(j)-1.0,float(j),amount);
        float radius=1.5/harmonic*weight;
        vec2 end=tip+radius*vec2(cos(harmonic*phase),sin(harmonic*phase));
        vec3 hue=mix(CYAN,PINK,float(j)/3.0);
        c+=glow(abs(length(p-tip)-radius),0.006,hue,0.5*weight,aa);
        c+=glow(lineDistance(p,tip,end),0.012,GOLD,0.65*weight,aa);
        c+=glow(length(p-end),0.027,WHITE,0.72*weight,aa);
        tip=end;
    }
    vec2 start=vec2(-1.15,tip.y);
    c+=glow(lineDistance(p,tip,start),0.005,GOLD,0.35*step(0.35,fract(p.x*10.0)),aa);
    c+=glow(length(p-start),0.04,WHITE,0.9,aa);
    c+=glow(lineDistance(p,vec2(-1.15,-0.6),vec2(6.1,-0.6)),0.005,CYAN,0.28,aa);
    if(p.x>-1.15 && p.x<6.1) {
        float a=phase-(p.x+1.15)*1.16;
        float y=-0.6+1.5*geoHarmonic(a,amount);
        float slope=1.74*geoHarmonicSlope(a,amount);
        float distanceToWave=abs(p.y-y)/sqrt(1.0+slope*slope);
        c+=glow(distanceToWave,0.02,CYAN,1.0,aa);
        // A thin fundamental remains under the gradually squared composite.
        float reference=-0.6+1.5*sin(a);
        c+=glow(abs(p.y-reference)/sqrt(1.0+pow(1.74*cos(a),2.0)),0.005,PINK,0.19,aa);
    }
    float baseline=-3.25;
    for(int j=0;j<4;j++) {
        float i=float(j), h=i*2.0+1.0;
        float weight=j==0?1.0:smoothstep(i-1.0,i,amount);
        float x=-1.1+i*1.75;
        float top=baseline+0.75/h*weight;
        float bar=lineDistance(p,vec2(x,baseline),vec2(x,top));
        c+=glow(bar,0.065,mix(CYAN,GOLD,i/3.0),0.55*weight,aa);
    }
    return c;
}

vec2 geoFinalPoint(float u,float local) {
    float sequence=mod(max(0.0,local)*0.95,4.0);
    float k=floor(sequence), blend=smoothstep(0.12,0.9,fract(sequence));
    float fromKind=k<0.5?5.0:k<1.5?4.0:k<2.5?1.0:0.0;
    float toKind=k<0.5?4.0:k<1.5?1.0:k<2.5?0.0:5.0;
    return mix(geoShape(u,fromKind),geoShape(u,toKind),blend);
}
vec3 geoFinale(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float local=t-102.0;
    vec2 q=rot(local*0.12)*p;
    float d=100.0,echoDistance=100.0,outerDistance=100.0,crossings=0.0;
    vec2 previous=geoFinalPoint(0.0,local)*1.28;
    vec2 echoPrevious=rot(0.13)*geoFinalPoint(0.0,local-0.32)*1.43;
    vec2 outerPrevious=rot(-0.11)*geoFinalPoint(0.0,local-0.66)*1.56;
    for(int j=1;j<=96;j++) {
        float u=float(j)/96.0;
        vec2 current=geoFinalPoint(u,local)*1.28;
        vec2 echoCurrent=rot(0.13)*geoFinalPoint(u,local-0.32)*1.43;
        vec2 outerCurrent=rot(-0.11)*geoFinalPoint(u,local-0.66)*1.56;
        d=min(d,lineDistance(q,previous,current));
        echoDistance=min(echoDistance,lineDistance(q,echoPrevious,echoCurrent));
        outerDistance=min(outerDistance,lineDistance(q,outerPrevious,outerCurrent));
        crossings+=geoRayCrossing(q,previous,current);
        previous=current;
        echoPrevious=echoCurrent;
        outerPrevious=outerCurrent;
    }
    float clearCenter=smoothstep(1.0,1.6,length(p));
    vec3 hue=mix(CYAN,PINK,0.5+0.5*sin(local*0.6));
    float inside=mod(crossings,2.0);
    c+=hue*inside*(0.055+0.035*smoothstep(1.5,3.5,length(p)))*clearCenter;
    c+=glow(outerDistance,0.006,CYAN,0.28,aa)*clearCenter;
    c+=glow(echoDistance,0.009,GOLD,0.5,aa)*clearCenter;
    c+=glow(d,0.024,hue,1.05,aa)*clearCenter;
    c+=WHITE*geoStroke(d,0.004,aa)*0.42*clearCenter;
    float headU=fract(local*0.31);
    float reverseU=fract(0.5-local*0.27);
    vec2 head=geoFinalPoint(headU,local)*1.28;
    vec2 reverseHead=rot(0.13)*geoFinalPoint(reverseU,local-0.32)*1.43;
    c+=glow(length(q-head),0.06,WHITE,1.0,aa)*clearCenter;
    c+=glow(length(q-reverseHead),0.055,GOLD,1.0,aa)*clearCenter;
    for(int j=1;j<=8;j++) {
        float delay=float(j)*0.012;
        float fade=1.0-float(j)/9.0;
        vec2 tail=geoFinalPoint(fract(headU-delay),local)*1.28;
        vec2 reverseTail=rot(0.13)*geoFinalPoint(fract(reverseU+delay),local-0.32)*1.43;
        c+=glow(length(q-tail),0.018+0.022*fade,PINK,0.3*fade,aa)*clearCenter;
        c+=glow(length(q-reverseTail),0.018+0.022*fade,GOLD,0.26*fade,aa)*clearCenter;
    }
    float r=length(p), a=atan(p.y,p.x);
    c+=glow(abs(r-(3.6+0.16*cos(8.0*a+local))),0.007,GOLD,0.55,aa);
    c+=glow(abs(r-3.94),0.004,CYAN,0.25,aa);
    for(int j=0;j<32;j++) {
        float i=float(j), angle=i*TAU/32.0+local*0.18;
        float radius=3.65+0.12*sin(i*2.3+local);
        vec2 at=vec2(cos(angle),sin(angle))*radius;
        c+=glow(length(p-at),0.022,mix(GOLD,CYAN,geoHash(i)),0.6,aa);
    }
    // Diagonal energy ribbons remain outside the reading area.
    vec2 ribbon=rot(-0.24)*p;
    float wave=sin(ribbon.x*0.8-local)*0.45;
    c+=glow(abs(abs(ribbon.y)-2.9-wave),0.008,PINK,0.25,aa)*smoothstep(2.2,4.4,abs(p.x));
    return c;
}

vec3 geometryAct(vec2 p,float t,float aa) {
    if(t>=12.0 && t<28.0) return geoMorphChain(p,t,aa)*geoGate(t,12.0,28.0);
    if(t>=48.0 && t<66.0) return geoEuler(p,t,aa)*geoGate(t,48.0,66.0);
    if(t>=66.0 && t<84.0) return geoCalculus(p,t,aa)*geoGate(t,66.0,84.0);
    if(t>=84.0 && t<102.0) return geoFourier(p,t,aa)*geoGate(t,84.0,102.0);
    if(t>=102.0 && t<114.0) return geoFinale(p,t,aa)*geoGate(t,102.0,114.0);
    return vec3(0.0);
}
