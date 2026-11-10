// The geometric score uses shared curve parameters throughout each transform.
// Six ribbon layers / 72 segments are the largest active path batch (432).
// No texture sampling, decorative particle fields, or expanding halo layers.

float geoGate(float t,float begin,float endTime) {
    return smoothstep(begin,begin+0.65,t)*(1.0-smoothstep(endTime-0.65,endTime,t));
}
float geoStroke(float d,float width,float aa) {
    return 1.0-smoothstep(width,width+aa,d);
}
float geoImpulse(float t,float center,float width) {
    float x=(t-center)/width;
    return exp(-x*x);
}
float geoReadingMask(vec2 p,vec2 center,vec2 halfSize) {
    vec2 edge=abs(p-center)-halfSize;
    return smoothstep(0.0,0.24,max(edge.x,edge.y));
}
float geoRayCrossing(vec2 p,vec2 a,vec2 b) {
    if((a.y>p.y)!=(b.y>p.y)) {
        float x=a.x+(p.y-a.y)*(b.x-a.x)/(b.y-a.y);
        return step(p.x,x);
    }
    return 0.0;
}
vec2 geoBezier(vec2 a,vec2 b,vec2 c,vec2 d,float u) {
    float v=1.0-u;
    return a*v*v*v+3.0*b*v*v*u+3.0*c*v*u*u+d*u*u*u;
}
vec2 geoPolygon(float u,float sides,float radius,float angle) {
    float slot=u*sides;
    float a=floor(slot)*TAU/sides+angle;
    float b=a+TAU/sides;
    return mix(vec2(cos(a),sin(a)),vec2(cos(b),sin(b)),fract(slot))*radius;
}
vec3 geoPanel(vec2 p,vec2 center,vec2 halfSize,float angle,vec3 hue,float alpha,float aa) {
    vec2 q=rot(angle)*(p-center);
    vec2 excess=abs(q)-halfSize;
    float sd=length(max(excess,vec2(0.0)))+min(max(excess.x,excess.y),0.0);
    float fill=1.0-smoothstep(-aa,aa,sd);
    return hue*fill*alpha+glow(abs(sd),0.012,hue,0.82,aa);
}

// A closed contour is expressed as twelve cubic Bezier pieces. Polygon
// controls lie on each edge; flower controls use the radial derivative.
// Interpolating these handles transforms the actual path and its control net.
vec2 geoShapeHandle(float segment,float role,float kind) {
    float a=segment*TAU/12.0+PI*0.5;
    float b=a+TAU/12.0;
    vec2 start=vec2(cos(a),sin(a));
    vec2 finish=vec2(cos(b),sin(b));
    if(kind<0.5) {
        if(role<0.5) return start*2.48;
        if(role<1.5) return (start+vec2(-sin(a),cos(a))*0.17553666)*2.48;
        if(role<2.5) return (finish-vec2(-sin(b),cos(b))*0.17553666)*2.48;
        return finish*2.48;
    }
    if(kind<2.5) {
        float sides=kind<1.5?4.0:3.0;
        float angle=kind<1.5?PI*0.25:PI*0.5;
        vec2 left=geoPolygon(segment/12.0,sides,2.85,angle);
        vec2 right=geoPolygon((segment+1.0)/12.0,sides,2.85,angle);
        return mix(left,right,role/3.0);
    }
    if(kind<3.5) {
        float ra=2.2+0.52*cos(6.0*a);
        float rb=2.2+0.52*cos(6.0*b);
        vec2 da=vec2(-sin(a),cos(a))*ra-start*(3.12*sin(6.0*a));
        vec2 db=vec2(-sin(b),cos(b))*rb-finish*(3.12*sin(6.0*b));
        if(role<0.5) return start*ra;
        if(role<1.5) return start*ra+da*(TAU/36.0);
        if(role<2.5) return finish*rb-db*(TAU/36.0);
        return finish*rb;
    }
    float u=segment/12.0, v=(segment+1.0)/12.0;
    vec2 left=vec2((u-0.5)*13.6,1.9*sin(u*TAU)+0.7*(u-0.5));
    vec2 right=vec2((v-0.5)*13.6,1.9*sin(v*TAU)+0.7*(v-0.5));
    vec2 dl=vec2(13.6,1.9*TAU*cos(u*TAU)+0.7)/36.0;
    vec2 dr=vec2(13.6,1.9*TAU*cos(v*TAU)+0.7)/36.0;
    if(role<0.5) return left;
    if(role<1.5) return left+dl;
    if(role<2.5) return right-dr;
    return right;
}
vec2 geoMovingHandle(float segment,float role,float evolution,float lane) {
    float kind=min(3.0,floor(evolution));
    float blend=clamp(evolution-kind,0.0,1.0);
    vec2 at=mix(geoShapeHandle(segment,role,kind),geoShapeHandle(segment,role,kind+1.0),blend);
    float spread=1.0-smoothstep(3.0,4.0,evolution);
    at*=0.73+lane*0.071;
    at=rot((lane-2.5)*0.045*spread-0.13)*at;
    at.x+=at.y*0.15*spread;
    return at+vec2(-0.6,-0.14)+(lane-2.5)*vec2(0.0,0.17)*(1.0-spread);
}
vec2 geoMorphPoint(float u,float evolution,float lane) {
    float piece=min(11.0,floor(u*12.0));
    float local=u*12.0-piece;
    return geoBezier(geoMovingHandle(piece,0.0,evolution,lane),
                     geoMovingHandle(piece,1.0,evolution,lane),
                     geoMovingHandle(piece,2.0,evolution,lane),
                     geoMovingHandle(piece,3.0,evolution,lane),local);
}
vec3 geoMorphChain(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float evolution=smoothstep(13.9,15.1,t)+smoothstep(17.1,18.3,t)
        +smoothstep(20.2,21.5,t)+smoothstep(24.0,26.7,t);
    for(int layer=0;layer<6;layer++) {
        float lane=float(layer);
        float delayed=max(0.0,evolution-(5.0-lane)*0.035*sin(PI*fract(evolution)));
        float d=100.0,crossings=0.0;
        vec2 previous=geoMovingHandle(0.0,0.0,delayed,lane);
        for(int piece=0;piece<12;piece++) {
            // Cache the four moving handles once per cubic, rather than
            // evaluating both target contours at every sampled point.
            vec2 a=geoMovingHandle(float(piece),0.0,delayed,lane);
            vec2 b=geoMovingHandle(float(piece),1.0,delayed,lane);
            vec2 e=geoMovingHandle(float(piece),2.0,delayed,lane);
            vec2 f=geoMovingHandle(float(piece),3.0,delayed,lane);
            for(int j=1;j<=6;j++) {
                vec2 current=geoBezier(a,b,e,f,float(j)/6.0);
                d=min(d,lineDistance(p,previous,current));
                crossings+=geoRayCrossing(p,previous,current);
                previous=current;
            }
        }
        vec3 hue=layer==0?GOLD:mix(vec3(0.055,0.32,0.65),CYAN,lane/5.0);
        float power=layer==5?1.12:layer==0?0.92:0.50;
        float closed=1.0-smoothstep(3.0,3.1,evolution);
        c+=hue*mod(crossings,2.0)*0.028*closed;
        c+=glow(d,layer==5?0.021:0.011,hue,power,aa);
    }
    // Four selected cubic pieces expose their actual handles. The handles
    // collapse onto polygon edges and bloom back out with the flower.
    float net=smoothstep(12.5,13.5,t)*(1.0-smoothstep(24.0,26.0,t));
    for(int j=0;j<4;j++) {
        float piece=float(j)*3.0;
        vec2 a=geoMovingHandle(piece,0.0,evolution,5.0);
        vec2 b=geoMovingHandle(piece,1.0,evolution,5.0);
        vec2 d=geoMovingHandle(piece,2.0,evolution,5.0);
        vec2 e=geoMovingHandle(piece,3.0,evolution,5.0);
        c+=glow(lineDistance(p,a,b),0.005,GOLD,0.40*net,aa);
        c+=glow(lineDistance(p,d,e),0.005,GOLD,0.40*net,aa);
        c+=glow(length(p-b),0.028,GOLD,0.90*net,aa);
        c+=glow(length(p-d),0.028,GOLD,0.90*net,aa);
        c+=glow(abs(length(p-a)-0.047),0.009,CYAN,0.86*net,aa);
    }
    return c;
}

// The same material point u first lies on a circle, then travels onto a sine
// graph. A travelling release makes the circumference visibly unroll.
vec2 geoEulerPoint(float u,float lane,float t) {
    float phase=(t-48.0)*0.74;
    float offset=lane-2.5;
    float unroll=smoothstep(50.5+u*2.7,57.0+u*2.7,t);
    float fuse=smoothstep(61.1,64.9,t);
    float angle=u*TAU+phase;
    vec2 circle=vec2(-1.75,-0.8)+vec2(cos(angle),sin(angle))*(2.02+offset*0.16);
    vec2 wave=vec2(-6.6+13.2*u,-0.85+1.8*sin(u*TAU*2.0+phase));
    wave.y+=offset*0.19*(1.0-fuse);
    wave.x+=offset*0.055*(1.0-fuse);
    return mix(circle,wave,unroll);
}
vec3 geoEuler(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float fuse=smoothstep(61.1,64.9,t);
    for(int layer=0;layer<6;layer++) {
        float lane=float(layer),d=100.0;
        vec2 previous=geoEulerPoint(0.0,lane,t);
        for(int j=1;j<=64;j++) {
            vec2 current=geoEulerPoint(float(j)/64.0,lane,t);
            d=min(d,lineDistance(p,previous,current));
            previous=current;
        }
        vec3 hue=layer==0?GOLD:mix(vec3(0.06,0.30,0.57),CYAN,lane/5.0);
        float power=layer==5?1.12:(layer==0?0.85:0.46)*(1.0-fuse);
        c+=glow(d,layer==5?0.022:0.011,hue,power,aa);
    }
    float u=fract((t-48.0)*0.095+0.2);
    vec2 at=geoEulerPoint(u,5.0,t);
    float release=smoothstep(50.5+u*2.7,57.0+u*2.7,t);
    vec2 foot=mix(vec2(-1.75,-0.8),vec2(at.x,-0.85),release);
    c+=glow(lineDistance(p,foot,at),0.008,GOLD,0.72,aa);
    c+=glow(length(p-at),0.048,GOLD,1.08,aa);
    float guide=smoothstep(54.5,59.0,t);
    c+=glow(lineDistance(p,vec2(-6.6,-0.85),vec2(6.6,-0.85)),0.004,CYAN,0.20*guide,aa);
    return c;
}

vec2 geoCalculusPoint(float u,float lane,float t) {
    float derivative=smoothstep(66.8+lane*0.06,67.6+lane*0.06,t);
    float integral=smoothstep(71.8,73.5,t);
    float x=mix(-1.0+2.0*u,u,integral);
    float y=mix(2.0*x*x*x,3.0*x*x,derivative);
    float baseline=mix(-1.45,-2.95,integral);
    float spread=(1.0-integral)*(1.0-smoothstep(72.7,74.0,t));
    return vec2(-5.75+11.5*u,baseline+y*mix(1.0,1.14,integral)+(lane-1.5)*0.15*spread);
}
vec3 geoCalculus(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float integral=smoothstep(71.8,73.5,t);
    float extraction=smoothstep(80.3,83.4,t);
    float baseline=mix(-1.45,-2.95,integral);
    for(int layer=0;layer<4;layer++) {
        float lane=float(layer),d=100.0;
        vec2 previous=geoCalculusPoint(0.0,lane,t);
        for(int j=1;j<=64;j++) {
            vec2 current=geoCalculusPoint(float(j)/64.0,lane,t);
            d=min(d,lineDistance(p,previous,current));
            previous=current;
        }
        float faded=1.0-smoothstep(72.7,74.0,t);
        float power=layer==3?1.12:(layer==0?0.65:0.35)*faded;
        c+=glow(d,layer==3?0.022:0.010,layer==0?GOLD:CYAN,power,aa);
    }
    float axes=1.0-extraction;
    c+=glow(lineDistance(p,vec2(-6.1,baseline),vec2(6.1,baseline)),0.005,CYAN,0.24*axes,aa);
    float ordinate=mix(0.0,-5.75,integral);
    c+=glow(lineDistance(p,vec2(ordinate,-3.35),vec2(ordinate,1.25)),0.005,CYAN,0.20*axes,aa);
    // A tangent remains attached to the changing curve before the area takes over.
    float cursor=0.5+0.36*sin((t-66.0)*0.55);
    vec2 at=geoCalculusPoint(cursor,3.0,t);
    vec2 before=geoCalculusPoint(cursor-0.002,3.0,t);
    vec2 after=geoCalculusPoint(cursor+0.002,3.0,t);
    vec2 tangent=normalize(after-before)*1.10;
    c+=glow(lineDistance(p,at-tangent,at+tangent),0.010,GOLD,0.9*(1.0-integral),aa);
    c+=glow(length(p-at),0.040,GOLD,1.0*(1.0-integral),aa);
    // Riemann cells refine in place. Their bases then move upward onto the
    // curve, so the area itself resolves into its continuous upper boundary.
    float count=8.0+floor(smoothstep(77.6,80.2,t)*24.0);
    if(integral>0.001 && p.x>=-5.75 && p.x<=5.75) {
        float x=(p.x+5.75)/11.5;
        float bin=min(count-1.0,floor(x*count));
        float sampleX=(bin+0.5)/count;
        float top=baseline+3.42*sampleX*sampleX;
        float bottom=mix(baseline,top,extraction);
        float cellLeft=-5.75+bin*11.5/count;
        float cellRight=cellLeft+11.5/count;
        float inside=smoothstep(bottom-aa,bottom+aa,p.y)*(1.0-smoothstep(top-aa,top+aa,p.y));
        c+=mix(vec3(0.04,0.25,0.48),CYAN,sampleX)*inside*0.24*integral;
        float wall=min(abs(p.x-cellLeft),abs(p.x-cellRight));
        c+=glow(wall,0.004,CYAN,0.35*integral*(1.0-extraction),aa)*inside;
        float cap=lineDistance(p,vec2(cellLeft,top),vec2(cellRight,top));
        c+=glow(cap,0.010,GOLD,0.74*integral*(1.0-extraction),aa);
    }
    return c;
}

float geoHarmonic(float a,float t) {
    return sin(a)+smoothstep(84.8,85.6,t)*sin(3.0*a)/3.0
        +smoothstep(89.8,90.6,t)*sin(5.0*a)/5.0
        +smoothstep(95.8,96.6,t)*sin(7.0*a)/7.0;
}
vec2 geoFourierPoint(float u,float lane,float t) {
    float phase=(t-84.0)*0.76;
    float angle=u*TAU*1.65-phase;
    float joined=smoothstep(84.3,87.1,t);
    float amplitude=mix(0.82,1.48,joined);
    vec2 total=vec2(-6.65+13.3*u,mix(0.2,-0.9,joined)+amplitude*geoHarmonic(angle,t));
    if(lane<0.5) return total;
    float harmonic=lane*2.0+1.0;
    float begin=lane<1.5?84.8:lane<2.5?89.8:95.8;
    float merge=smoothstep(begin,begin+0.8,t);
    vec2 component=vec2(total.x,0.1-lane*1.10+1.5*sin(harmonic*angle)/harmonic);
    return mix(component,total,merge);
}
vec3 geoFourier(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    for(int layer=0;layer<4;layer++) {
        float lane=float(layer),d=100.0;
        vec2 previous=geoFourierPoint(0.0,lane,t);
        for(int j=1;j<=96;j++) {
            vec2 current=geoFourierPoint(float(j)/96.0,lane,t);
            d=min(d,lineDistance(p,previous,current));
            previous=current;
        }
        float begin=layer==1?84.8:layer==2?89.8:95.8;
        float merge=smoothstep(begin,begin+0.8,t);
        float anticipation=smoothstep(begin-1.5,begin-0.25,t);
        float power=layer==0?1.14:(0.43+0.5*anticipation)*(1.0-merge);
        vec3 hue=layer==0?CYAN:mix(vec3(0.11,0.48,0.74),GOLD,anticipation);
        c+=glow(d,layer==0?0.024:0.013,hue,power,aa);
        if(layer>0) {
            // Shared abscissae make addition legible while each strand joins.
            float link=sin(PI*merge);
            for(int j=0;j<3;j++) {
                float u=0.17+float(j)*0.33;
                vec2 source=geoFourierPoint(u,lane,t);
                vec2 target=geoFourierPoint(u,0.0,t);
                c+=glow(lineDistance(p,source,target),0.006,GOLD,0.36*link,aa);
            }
        }
    }
    float baseline=mix(0.2,-0.9,smoothstep(84.3,87.1,t));
    c+=glow(lineDistance(p,vec2(-6.65,baseline),vec2(6.65,baseline)),0.004,CYAN,0.16,aa);
    return c;
}

// The closing shell inherits the open wave's vertex order, closes, folds into
// a diamond, blooms, then settles. Each layer follows with a small delay.
vec2 geoFinalPoint(float u,float lane,float t) {
    float local=t-102.0;
    float delay=(5.0-lane)*0.12;
    float a=u*TAU;
    float scale=0.83+lane*0.038;
    vec2 shell=vec2(6.15*cos(a)+0.35*cos(3.0*a),2.5*sin(a)+0.58*sin(3.0*a));
    vec2 diamond=geoPolygon(u,4.0,1.0,0.0)*vec2(6.5,3.1);
    vec2 bloom=vec2(cos(a)*6.2,sin(a)*2.65)*(1.0+0.14*cos(4.0*a));
    float fold=smoothstep(105.0+delay,106.3+delay,t)*(1.0-smoothstep(107.0+delay,108.5+delay,t));
    float flower=smoothstep(107.0+delay,108.5+delay,t)*(1.0-smoothstep(110.6+delay,112.7+delay,t));
    vec2 target=mix(mix(shell,diamond,fold),bloom,flower)*scale;
    target.x+=target.y*0.26;
    target.y+=target.x*0.035;
    float gather=smoothstep(102.1+delay,104.4+delay,t);
    if(gather>=1.0) return target;
    float waveAngle=u*TAU*1.65-(t-84.0)*0.76;
    vec2 source=vec2(-6.65+13.3*u,-0.9+1.48*geoHarmonic(waveAngle,102.0));
    source.y+=(lane-2.5)*0.43;
    return mix(source,target,gather);
}
vec3 geoFinale(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    for(int layer=0;layer<6;layer++) {
        float lane=float(layer),d=100.0,crossings=0.0;
        vec2 previous=geoFinalPoint(0.0,lane,t);
        for(int j=1;j<=72;j++) {
            vec2 current=geoFinalPoint(float(j)/72.0,lane,t);
            d=min(d,lineDistance(p,previous,current));
            crossings+=geoRayCrossing(p,previous,current);
            previous=current;
        }
        vec3 hue=layer==0?GOLD:mix(vec3(0.04,0.24,0.52),CYAN,lane/5.0);
        float power=layer==0?0.95:layer==5?1.12:0.55;
        float closed=smoothstep(104.8,105.5,t);
        c+=hue*mod(crossings,2.0)*(0.018+lane*0.004)*closed;
        c+=glow(d,layer==5?0.023:0.012,hue,power,aa);
    }
    return c*geoReadingMask(p,vec2(0.0,0.1),vec2(3.35,0.79));
}
vec2 geoIntroPoint(float u,float lane,float t) {
    float offset=lane-2.5;
    float gather=smoothstep(0.0,2.0,t);
    vec2 linePoint=vec2((u-0.5)*17.5,(u-0.5)*7.2+offset*mix(0.62,0.11,gather));
    float angle=-PI*0.85+u*TAU*1.05;
    float radius=2.1+2.4*u+offset*0.14;
    vec2 coil=vec2(cos(angle)*1.27,sin(angle)*0.72)*radius;
    float a=u*TAU;
    vec2 shell=vec2(6.15*cos(a)+0.35*cos(3.0*a),2.5*sin(a)+0.58*sin(3.0*a));
    shell*=0.86+lane*0.045;
    shell.x+=shell.y*0.22;
    vec2 fan=geoBezier(vec2(-8.0,-2.9-offset*0.16),vec2(-3.4,6.0+offset*0.6),
                      vec2(3.4,-6.0-offset*0.6),vec2(8.0,2.9+offset*0.16),u);
    vec2 curvePoint=mix(linePoint,coil,smoothstep(1.65+lane*0.07,4.4+lane*0.07,t));
    curvePoint=mix(curvePoint,shell,smoothstep(5.25+lane*0.06,7.35+lane*0.06,t));
    curvePoint=mix(curvePoint,fan,smoothstep(8.3+lane*0.08,11.55+lane*0.08,t));
    return curvePoint;
}
vec2 geoClosingPoint(float u,float lane,float t) {
    vec2 source=geoFinalPoint(u,lane,113.95);
    float scale=0.89+lane*0.031;
    vec2 target;
    if(u<0.5) {
        target=geoBezier(vec2(7.6,0.0),vec2(6.4,4.8),vec2(-6.4,4.8),vec2(-7.6,0.0),u*2.0);
    } else {
        target=geoBezier(vec2(-7.6,0.0),vec2(-6.4,-4.7),vec2(6.4,-4.7),vec2(7.6,0.0),(u-0.5)*2.0);
    }
    target*=scale;
    float settle=smoothstep(114.0+lane*0.08,117.3+lane*0.08,t);
    return mix(source,target,settle);
}
vec3 geometryAct(vec2 p,float t,float aa) {
    if(t>=12.0 && t<28.0) return geoMorphChain(p,t,aa)*geoGate(t,12.0,28.0);
    if(t>=48.0 && t<66.0) return geoEuler(p,t,aa)*geoGate(t,48.0,66.0);
    if(t>=66.0 && t<84.0) return geoCalculus(p,t,aa)*geoGate(t,66.0,84.0);
    if(t>=84.0 && t<102.0) return geoFourier(p,t,aa)*geoGate(t,84.0,102.0);
    if(t>=102.0 && t<114.0) return geoFinale(p,t,aa)*smoothstep(102.0,102.65,t);
    return vec3(0.0);
}
