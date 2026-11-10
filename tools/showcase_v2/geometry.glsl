// The geometric score uses shared curve parameters throughout each transform.
// At most five 96-segment ribbons plus a small control net per active act.
// Recursive structure uses five bounded inverse-IFS steps, without textures.

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
// Spectral pigment travels along the material parameter, not screen position.
vec3 geoPalette(float phase) {
    vec3 pigment=0.53+0.47*cos(TAU*(phase+vec3(0.02,0.31,0.64)));
    return mix(pigment,vec3(0.08,0.62,0.85),0.10);
}
void geoTrack(vec2 p,vec2 a,vec2 b,float ua,float ub,inout float nearest,inout float parameter) {
    vec2 edge=b-a;
    float fraction=clamp(dot(p-a,edge)/max(dot(edge,edge),0.000001),0.0,1.0);
    float d=length(p-a-edge*fraction);
    if(d<nearest) { nearest=d; parameter=mix(ua,ub,fraction); }
}
vec3 geoRibbon(float d,float parameter,float lane,float t,float width,float power,float aa) {
    vec3 hue=geoPalette(parameter*1.35-lane*0.105-t*0.065);
    float depth=0.70+0.30*cos(parameter*TAU*3.0+lane*0.72-t*0.8);
    float current=pow(0.5+0.5*cos(TAU*(parameter-t*0.13+lane*0.11)),10.0);
    return glow(d,width,hue,power*(depth+0.30*current),aa)
        +hue*exp(-d*11.0)*0.035*power;
}
float geoTriangleDistance(vec2 p) {
    p.x=abs(p.x)-0.8660254;
    p.y+=0.5;
    if(p.x+1.7320508*p.y>0.0) p=vec2(p.x-1.7320508*p.y,-1.7320508*p.x-p.y)*0.5;
    p.x-=clamp(p.x,-1.7320508,0.0);
    return -length(p)*sign(p.y);
}
// Each inverse step selects one of three half-size triangle copies. The
// five levels are an actual finite Sierpinski IFS; angular folding unfolds
// those copies into six petal sectors without adding per-cell draw loops.
vec3 geoFractalLace(vec2 p,float t,float depth,float bloom,float worldScale,float aa) {
    vec2 q=rot(0.13*sin(t*0.23))*p/worldScale;
    float angle=atan(q.y,q.x);
    float folded=abs(mod(angle+PI/6.0,PI/3.0)-PI/6.0);
    vec2 petal=vec2(sin(folded),cos(folded))*length(q);
    q=mix(q,petal,bloom);
    vec3 c=vec3(0.0);
    float scale=worldScale,ancestry=0.0,valid=1.0;
    for(int level=0;level<5;level++) {
        float i=float(level);
        float reveal=smoothstep(i-0.15,i+0.75,depth);
        float sd=geoTriangleDistance(q);
        float d=abs(sd)*scale;
        vec3 hue=geoPalette(ancestry*0.13+i*0.12-t*0.045+length(p)*0.035);
        float ink=1.0-smoothstep(-aa,aa,sd*scale);
        c+=glow(d,mix(0.012,0.004,i/4.0),hue,(0.55-i*0.065)*reveal*valid,aa);
        c+=hue*0.012*ink*reveal*valid;
        valid*=1.0-smoothstep(aa*2.0,aa*4.0,sd*scale);
        vec2 vertex=vec2(0.0,1.0);
        float nearest=dot(q-vertex,q-vertex),branch=0.0;
        vec2 second=vec2(-0.8660254,-0.5);
        float testDistance=dot(q-second,q-second);
        if(testDistance<nearest) { vertex=second; nearest=testDistance; branch=1.0; }
        second=vec2(0.8660254,-0.5);
        testDistance=dot(q-second,q-second);
        if(testDistance<nearest) { vertex=second; branch=2.0; }
        ancestry=ancestry*0.55+branch;
        q=q*2.0-vertex;
        q=rot(0.045*sin(t*0.52+i*0.9)*bloom)*q;
        scale*=0.5;
    }
    return c;
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
vec3 geoFacet(vec2 p,vec2 a,vec2 b,vec2 c,vec3 hue,float strength,float aa) {
    vec2 ab=b-a,bc=c-b,ca=a-c;
    vec2 ap=p-a,bp=p-b,cp=p-c;
    float x=ab.x*ap.y-ab.y*ap.x;
    float y=bc.x*bp.y-bc.y*bp.x;
    float z=ca.x*cp.y-ca.y*cp.x;
    float inside=max(step(0.0,min(x,min(y,z))),step(max(x,max(y,z)),0.0));
    float area=abs(ab.x*(c.y-a.y)-ab.y*(c.x-a.x));
    inside*=smoothstep(0.00001,0.0003,area);
    float edge=min(lineDistance(p,a,b),min(lineDistance(p,b,c),lineDistance(p,c,a)));
    return hue*strength*inside+glow(edge,0.006,hue,strength*1.3,aa);
}
vec3 geoPanel(vec2 p,vec2 center,vec2 halfSize,float angle,vec3 hue,float alpha,float t,float aa) {
    vec2 q=rot(angle)*(p-center);
    vec2 excess=abs(q)-halfSize;
    float sd=length(max(excess,vec2(0.0)))+min(max(excess.x,excess.y),0.0);
    float fill=1.0-smoothstep(-aa,aa,sd);
    vec2 cell=q/(halfSize*2.0)+0.5;
    float keep=1.0,cellScale=1.0;
    vec3 lace=vec3(0.0);
    // A three-level Sierpinski carpet is carried in each tile's local frame,
    // so its eight self-similar children rotate and assemble with the area.
    for(int level=0;level<3;level++) {
        float i=float(level);
        vec2 local=abs(fract(cell)-0.5)-vec2(1.0/6.0);
        float hole=max(local.x,local.y);
        float metric=2.0*min(halfSize.x,halfSize.y)/cellScale;
        float detail=0.5+0.5*sin(t*0.7-i*0.85);
        float cut=(1.0-smoothstep(-aa,aa,hole*metric))*0.67;
        vec3 pigment=geoPalette(i*0.14-t*0.045+center.x*0.025);
        lace+=glow(abs(hole)*metric,0.004,pigment,0.32*keep*(0.65+0.35*detail),aa);
        keep*=1.0-cut;
        cell*=3.0;
        cellScale*=3.0;
    }
    vec3 pigment=mix(hue,geoPalette(t*0.04+q.x*0.07+q.y*0.09),0.46);
    return pigment*fill*alpha*(0.42+0.58*keep)+lace*fill
        +glow(abs(sd),0.015,pigment,0.90,aa);
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
    at*=0.60+lane*0.118;
    at=rot((lane-2.0)*0.10*spread-0.13)*at;
    at.x+=at.y*0.15*spread;
    return at+vec2(-0.6,-0.14)+(lane-2.0)*vec2(0.0,0.24)*(1.0-spread);
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
    float charge=geoImpulse(t,17.65,0.50)+geoImpulse(t,22.45,0.48);
    float release=geoImpulse(t,18.35,0.64)+geoImpulse(t,23.15,0.68);
    float camera=1.0+release*0.13;
    vec2 q=rot(0.055*sin(t*0.5))*(p/camera);
    q.y/=1.0-0.32*charge;
    q.x+=abs(q.y)*charge*0.20;
    float localAA=aa/(camera*(1.0-0.32*charge));
    float outerInside=0.0;
    for(int layer=0;layer<5;layer++) {
        float lane=float(layer);
        float delayed=max(0.0,evolution-(4.0-lane)*0.065*sin(PI*fract(evolution)));
        float d=100.0,along=0.0,crossings=0.0;
        vec2 previous=geoMovingHandle(0.0,0.0,delayed,lane);
        for(int piece=0;piece<12;piece++) {
            vec2 a=geoMovingHandle(float(piece),0.0,delayed,lane);
            vec2 b=geoMovingHandle(float(piece),1.0,delayed,lane);
            vec2 e=geoMovingHandle(float(piece),2.0,delayed,lane);
            vec2 f=geoMovingHandle(float(piece),3.0,delayed,lane);
            for(int j=1;j<=8;j++) {
                float u=(float(piece)+float(j)/8.0)/12.0;
                vec2 current=geoBezier(a,b,e,f,float(j)/8.0);
                geoTrack(q,previous,current,u-1.0/96.0,u,d,along);
                crossings+=geoRayCrossing(q,previous,current);
                previous=current;
            }
        }
        vec3 hue=geoPalette(along*1.35-lane*0.105-t*0.065);
        float closed=1.0-smoothstep(3.0,3.15,evolution);
        c+=hue*mod(crossings,2.0)*0.022*closed;
        c+=geoRibbon(d,along,lane,t,layer==4?0.028:0.014,layer==4?1.12:0.68,localAA);
        if(layer==4) outerInside=mod(crossings,2.0);
    }
    float net=smoothstep(12.5,13.5,t)*(1.0-smoothstep(24.0,26.0,t));
    for(int j=0;j<4;j++) {
        float piece=float(j)*3.0;
        vec2 a=geoMovingHandle(piece,0.0,evolution,4.0);
        vec2 b=geoMovingHandle(piece,1.0,evolution,4.0);
        vec2 d=geoMovingHandle(piece,2.0,evolution,4.0);
        vec2 e=geoMovingHandle(piece,3.0,evolution,4.0);
        vec3 hue=geoPalette(float(j)*0.22-t*0.065);
        c+=glow(lineDistance(q,a,b),0.006,hue,0.52*net,localAA);
        c+=glow(lineDistance(q,d,e),0.006,hue,0.52*net,localAA);
        c+=glow(length(q-b),0.030,hue,0.95*net,localAA);
        c+=glow(length(q-d),0.030,hue,0.95*net,localAA);
    }
    float depth=1.0+4.0*smoothstep(12.8,16.3,t)-charge*1.25;
    float bloom=clamp(abs(evolution-2.0),0.0,1.0);
    float laceLife=smoothstep(12.3,13.4,t)*(1.0-smoothstep(23.8,26.0,t));
    c+=geoFractalLace(q-vec2(-0.6,-0.14),t,depth,bloom,2.95,localAA)*laceLife*outerInside;
    // Broad prismatic faces hinge with the outer contour during each beat.
    for(int j=0;j<6;j++) {
        float u=float(j)/6.0;
        vec2 a=geoMorphPoint(u,evolution,4.0);
        vec2 b=geoMorphPoint(u+1.0/6.0,evolution,4.0);
        vec2 hinge=vec2(sin(t+float(j)),cos(t*0.7+float(j)))*0.65*charge;
        c+=geoFacet(q,hinge,a,b,geoPalette(u-t*0.065),
                    (0.025+0.12*charge+0.045*release)*laceLife,localAA);
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
    wave.y+=offset*0.24*(1.0-fuse);
    wave.y+=sin(u*TAU*4.0-phase)*offset*0.17*sin(PI*unroll);
    wave.x+=offset*0.055*(1.0-fuse);
    return mix(circle,wave,unroll);
}
vec3 geoEuler(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float fuse=smoothstep(61.1,64.9,t);
    for(int layer=0;layer<6;layer++) {
        float lane=float(layer),d=100.0,along=0.0;
        vec2 previous=geoEulerPoint(0.0,lane,t);
        for(int j=1;j<=64;j++) {
            float u=float(j)/64.0;
            vec2 current=geoEulerPoint(u,lane,t);
            geoTrack(p,previous,current,u-1.0/64.0,u,d,along);
            previous=current;
        }
        float power=layer==5?1.12:0.66*(1.0-fuse);
        c+=geoRibbon(d,along,lane,t,layer==5?0.025:0.013,power,aa);
    }
    float loom=smoothstep(51.0,53.0,t)*(1.0-smoothstep(60.0,63.0,t));
    for(int j=0;j<12;j++) {
        float u=(float(j)+0.5)/12.0;
        vec2 a=geoEulerPoint(u,0.0,t),b=geoEulerPoint(u,5.0,t);
        c+=glow(lineDistance(p,a,b),0.006,geoPalette(u-t*0.065),0.36*loom,aa);
    }
    float u=fract((t-48.0)*0.095+0.2);
    vec2 at=geoEulerPoint(u,5.0,t);
    float release=smoothstep(50.5+u*2.7,57.0+u*2.7,t);
    vec2 foot=mix(vec2(-1.75,-0.8),vec2(at.x,-0.85),release);
    c+=glow(lineDistance(p,foot,at),0.010,GOLD,0.72,aa);
    c+=glow(length(p-at),0.050,GOLD,1.08,aa);
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
        float lane=float(layer),d=100.0,along=0.0;
        vec2 previous=geoCalculusPoint(0.0,lane,t);
        for(int j=1;j<=64;j++) {
            float u=float(j)/64.0;
            vec2 current=geoCalculusPoint(u,lane,t);
            geoTrack(p,previous,current,u-1.0/64.0,u,d,along);
            previous=current;
        }
        float faded=1.0-smoothstep(72.7,74.0,t);
        float power=layer==3?1.12:(layer==0?0.65:0.35)*faded;
        c+=geoRibbon(d,along,lane,t,layer==3?0.025:0.012,power,aa);
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
        vec3 areaHue=geoPalette(sampleX*0.9-t*0.045);
        c+=areaHue*inside*0.30*integral;
        float wall=min(abs(p.x-cellLeft),abs(p.x-cellRight));
        c+=glow(wall,0.005,areaHue,0.50*integral*(1.0-extraction),aa)*inside;
        float cap=lineDistance(p,vec2(cellLeft,top),vec2(cellRight,top));
        c+=glow(cap,0.012,areaHue,0.82*integral*(1.0-extraction),aa);
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
        float lane=float(layer),d=100.0,along=0.0;
        vec2 previous=geoFourierPoint(0.0,lane,t);
        for(int j=1;j<=96;j++) {
            float u=float(j)/96.0;
            vec2 current=geoFourierPoint(u,lane,t);
            geoTrack(p,previous,current,u-1.0/96.0,u,d,along);
            previous=current;
        }
        float begin=layer==1?84.8:layer==2?89.8:95.8;
        float merge=smoothstep(begin,begin+0.8,t);
        float anticipation=smoothstep(begin-1.5,begin-0.25,t);
        float power=layer==0?1.14:(0.43+0.5*anticipation)*(1.0-merge);
        c+=geoRibbon(d,along,lane,t,layer==0?0.028:0.015,power,aa);
        if(layer>0 && p.x>-6.65 && p.x<6.65) {
            float x=(p.x+6.65)/13.3;
            float harmonic=lane*2.0+1.0;
            float angle=x*TAU*1.65-(t-84.0)*0.76;
            float y=0.1-lane*1.10+1.5*sin(harmonic*angle)/harmonic;
            float slope=1.5*TAU*1.65/13.3*cos(harmonic*angle);
            float trace=abs(p.y-y)/sqrt(1.0+slope*slope);
            float ghost=merge*(1.0-smoothstep(99.0,101.5,t));
            c+=geoRibbon(trace,x,lane,t,0.006,0.24*ghost,aa);
        }
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

// A five-strand torus-knot projection inherits the same wave samples. Its
// fold, six-petal bloom, and finer radial copies all retain vertex identity.
vec2 geoFinalPoint(float u,float lane,float t) {
    float local=t-102.0;
    float delay=(4.0-lane)*0.10;
    float a=u*TAU+lane*0.052;
    float twist=0.38*sin(local*0.57);
    float radius=3.45+0.68*cos(3.0*a+twist);
    vec2 knot=vec2(radius*cos(2.0*a)*1.57,radius*sin(2.0*a)*0.71+0.30*sin(3.0*a+twist));
    vec2 diamond=geoPolygon(u,4.0,1.0,0.0)*vec2(6.6,3.1);
    float petal=1.0+0.17*cos(6.0*a+twist)+0.055*cos(12.0*a+twist*2.0)
        +0.018*cos(24.0*a+twist*4.0);
    vec2 rose=vec2(cos(a)*5.9,sin(a)*2.65)*petal;
    float fold=smoothstep(105.0+delay,106.1+delay,t)*(1.0-smoothstep(106.7+delay,108.0+delay,t));
    float flower=smoothstep(107.0+delay,108.6+delay,t)
        *(1.0-0.55*smoothstep(109.3+delay,110.5+delay,t))+0.55*smoothstep(111.0+delay,112.8+delay,t);
    vec2 target=mix(mix(knot,diamond,fold),rose,clamp(flower,0.0,1.0))*(0.77+lane*0.055);
    float charge=geoImpulse(t,105.65,0.36)+geoImpulse(t,110.25,0.36);
    float release=geoImpulse(t,106.2,0.54)+geoImpulse(t,110.85,0.54);
    target.y*=1.0-0.27*charge;
    target*=1.0+0.08*release;
    target.x+=target.y*0.18;
    float gather=smoothstep(102.05+delay,104.35+delay,t);
    if(gather>=1.0) return target;
    float waveAngle=u*TAU*1.65-(t-84.0)*0.76;
    vec2 source=vec2(-6.65+13.3*u,-0.9+1.48*geoHarmonic(waveAngle,102.0));
    source.y+=(lane-2.0)*0.48;
    return mix(source,target,gather);
}
vec3 geoFinale(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float laceLife=smoothstep(104.1,105.5,t);
    float depth=1.2+3.8*smoothstep(104.3,109.0,t);
    c+=geoFractalLace(p*vec2(0.56,1.0),t,depth,1.0,3.2,aa)*laceLife*0.85;
    for(int layer=0;layer<5;layer++) {
        float lane=float(layer),d=100.0,along=0.0,crossings=0.0;
        vec2 previous=geoFinalPoint(0.0,lane,t);
        for(int j=1;j<=96;j++) {
            float u=float(j)/96.0;
            vec2 current=geoFinalPoint(u,lane,t);
            geoTrack(p,previous,current,u-1.0/96.0,u,d,along);
            crossings+=geoRayCrossing(p,previous,current);
            previous=current;
        }
        vec3 hue=geoPalette(along*1.35-lane*0.105-t*0.065);
        c+=hue*mod(crossings,2.0)*(0.014+lane*0.002)*laceLife;
        c+=geoRibbon(d,along,lane,t,layer==4?0.030:0.015,layer==4?1.18:0.75,aa);
    }
    float charge=geoImpulse(t,105.65,0.48)+geoImpulse(t,110.25,0.48);
    for(int j=0;j<5;j++) {
        float u=float(j)/5.0;
        vec2 a=geoFinalPoint(u,4.0,t),b=geoFinalPoint(u+0.10,4.0,t);
        vec2 inner=geoFinalPoint(u+0.05,0.0,t);
        c+=geoFacet(p,a,b,inner,geoPalette(u-t*0.065),(0.055+0.14*charge)*laceLife,aa);
    }
    return c;
}
vec2 geoIntroPoint(float u,float lane,float t) {
    float offset=lane-2.0;
    float gather=smoothstep(0.0,1.8,t);
    vec2 linePoint=vec2((u-0.5)*18.0,(u-0.5)*7.4+offset*mix(0.74,0.14,gather));
    float a=u*TAU+lane*0.055;
    float twist=0.34*sin(t*0.73);
    float radius=3.3+0.72*cos(3.0*a+twist)+offset*0.11;
    vec2 knot=vec2(radius*cos(2.0*a)*1.58,radius*sin(2.0*a)*0.74+0.38*sin(3.0*a+twist));
    float petals=1.0+0.17*cos(5.0*a-t*0.22)+0.055*cos(10.0*a-t*0.44);
    vec2 flower=vec2(cos(a)*5.85,sin(a)*2.7)*petals*(0.82+lane*0.045);
    flower.x+=flower.y*0.20;
    vec2 fan=geoBezier(vec2(-8.0,-2.9-offset*0.24),vec2(-3.4,6.8+offset*0.8),
                      vec2(3.4,-6.8-offset*0.8),vec2(8.0,2.9+offset*0.24),u);
    fan.y+=sin(u*TAU*6.0-t)*0.10*offset;
    vec2 curvePoint=mix(linePoint,knot,smoothstep(1.2+lane*0.08,3.7+lane*0.08,t));
    curvePoint=mix(curvePoint,flower,smoothstep(5.15+lane*0.06,7.25+lane*0.06,t));
    curvePoint=mix(curvePoint,fan,smoothstep(8.35+lane*0.08,11.6+lane*0.08,t));
    float charge=geoImpulse(t,4.65,0.4)+geoImpulse(t,8.45,0.4);
    float release=geoImpulse(t,5.2,0.65)+geoImpulse(t,9.0,0.65);
    curvePoint.y*=1.0-0.30*charge;
    curvePoint*=1.0+0.08*release;
    return curvePoint;
}
vec2 geoClosingPoint(float u,float lane,float t) {
    vec2 source=geoFinalPoint(u,lane,113.95);
    float scale=0.86+lane*0.040;
    vec2 target;
    if(u<0.5) {
        target=geoBezier(vec2(7.6,0.0),vec2(6.4,4.8),vec2(-6.4,4.8),vec2(-7.6,0.0),u*2.0);
    } else {
        target=geoBezier(vec2(-7.6,0.0),vec2(-6.4,-4.7),vec2(6.4,-4.7),vec2(7.6,0.0),(u-0.5)*2.0);
    }
    target*=scale;
    target.y+=0.045*sin(u*TAU*6.0+(t-114.0)*0.4)*sin(u*PI);
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
