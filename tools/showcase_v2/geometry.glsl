// V9: spectral constructions. Each chapter continuously deforms its material
// coordinates; repeated detail uses analytic circles, folds and similarities.
float geoLife(float t,float a,float b) {
    return smoothstep(a,a+0.65,t)*(1.0-smoothstep(b-0.65,b,t));
}
float geoInk(float d,float width,float aa) { return 1.0-smoothstep(width,width+aa,d); }
float geoCross(vec2 a,vec2 b) { return a.x*b.y-a.y*b.x; }
vec3 geoRibbon(float d,float along,float lane,float t,float width,float power,float aa) {
    vec3 hue=geoPalette(along*0.78+lane*0.135-t*0.037);
    float running=pow(0.5+0.5*cos(along*TAU*3.0-t*1.9+lane),10.0);
    return glow(d,width,hue,power,aa)+glow(d,width*0.55,WHITE,power*0.18*running,aa);
}
void geoTrack(vec2 p,vec2 a,vec2 b,float ua,float ub,inout float d,inout float along) {
    vec2 e=b-a;
    float u=clamp(dot(p-a,e)/max(dot(e,e),0.000001),0.0,1.0);
    vec2 offset=p-a-u*e;
    float q=dot(offset,offset);
    if(q<d) { d=q; along=mix(ua,ub,u); }
}
// Squared lower bound to a whole group of original polyline segments. A curve
// with |C''(u)| <= curvature lies inside its endpoint box expanded by
// curvature * (ub-ua)^2 / 8. Rejecting that box cannot discard a closer segment.
float geoBoxDistance2(vec2 p,vec2 a,vec2 b,vec2 padding) {
    vec2 gap=max(max(min(a,b)-p,p-max(a,b))-padding,vec2(0.0));
    return dot(gap,gap);
}
float geoSearchDistance2(float aa) {
    // At one world unit the original glow contributes < 2e-10 per ribbon.
    // Include the complete AA support even on an unusually small viewport.
    float radius=max(1.0,aa+0.05);
    return radius*radius;
}
float geoTriangle(vec2 p,vec2 a,vec2 b,vec2 c,float aa) {
    float orient=sign(geoCross(b-a,c-a));
    float da=orient*geoCross(b-a,p-a)/max(length(b-a),0.0001);
    float db=orient*geoCross(c-b,p-b)/max(length(c-b),0.0001);
    float dc=orient*geoCross(a-c,p-c)/max(length(a-c),0.0001);
    return smoothstep(-aa,aa,min(da,min(db,dc)))*smoothstep(0.0001,0.003,abs(geoCross(b-a,c-a)));
}
// All rings/ticks are analytic. They frame the ink without clearing its field.
vec3 geoOrbits(vec2 p,float t,float radius,float power,float aa) {
    vec2 q=p/vec2(1.78,1.0);
    float r=length(q),a=atan(q.y,q.x);
    vec3 c=vec3(0.0);
    for(int lane=0;lane<3;lane++) {
        float k=float(lane),rad=radius+k*0.13;
        float sweep=smoothstep(-0.35,0.10,sin(a*(2.0+k)-t*(0.22+k*0.07)+k));
        c+=glow(abs(r-rad),0.006,geoPalette(a/TAU-k*0.17-t*0.025),power*(0.16+0.42*sweep),aa);
    }
    float tick=abs(sin((a-t*0.025)*48.0))*max(r,0.1)/48.0;
    float band=smoothstep(radius+0.35,radius+0.38,r)*(1.0-smoothstep(radius+0.47,radius+0.49,r));
    c+=GOLD*geoInk(tick,0.005,aa)*band*power*0.52;
    for(int j=0;j<6;j++) {
        float angle=float(j)*TAU/6.0+t*0.24;
        vec2 node=vec2(cos(angle)*1.78,sin(angle))*(radius+0.13);
        c+=glow(length(p-node),0.030,geoPalette(float(j)/6.0-t*0.03),power*0.90,aa);
    }
    return c;
}
vec2 geoOpeningCurve(float u,float lane,float t,float release) {
    float envelope=sin(PI*u);
    float y=-2.25+(lane-2.0)*0.085;
    y+=envelope*(0.10+0.24*release)*sin(u*TAU*1.5-t*0.65+lane*0.5);
    y+=release*envelope*0.45*sin(u*TAU+lane*0.22);
    return vec2(mix(-6.3,6.3,u),y);
}
vec3 geoOpening(vec2 p,float t,float aa) {
    float reveal=smoothstep(0.5,5.3,t),release=smoothstep(9.0,13.4,t);
    vec3 c=geoOrbits(p-vec2(0.0,0.1),t,3.35,0.26*smoothstep(3.5,8.0,t),aa);
    for(int lane=0;lane<5;lane++) {
        float k=float(lane),along=0.0;
        vec2 previous=vec2(-6.3,-2.25+(k-2.0)*0.085);
        float d=min(dot(p-previous,p-previous),geoSearchDistance2(aa));
        float curvature=(16.0*(0.10+0.24*release)+9.0*0.45*release)*(PI*PI);
        for(int block=0;block<8;block++) {
            float ua=min(float(block*8)/64.0,reveal),ub=min(float(block*8+8)/64.0,reveal);
            if(ub<=ua) break;
            vec2 last=geoOpeningCurve(ub,k,t,release);
            vec2 padding=vec2(0.00002,curvature*(ub-ua)*(ub-ua)*0.125+0.00002);
            if(geoBoxDistance2(p,previous,last,padding)<=d) {
                for(int j=1;j<=8;j++) {
                    float u=min(float(block*8+j)/64.0,reveal);
                    vec2 current=j==8?last:geoOpeningCurve(u,k,t,release);
                    geoTrack(p,previous,current,max(0.0,u-1.0/64.0),u,d,along);
                    previous=current;
                }
            }
            previous=last;
        }
        c+=geoRibbon(sqrt(d),along,k,t,lane==2?0.017:0.008,lane==2?0.98:0.60,aa);
    }
    return c*(1.0-smoothstep(13.0,14.0,t));
}
struct GeoPetal {
    vec3 morph;
    mat2 transform;
    vec2 shift;
    float phase;
    float scale;
};
GeoPetal geoPetalSetup(float lane,float t) {
    GeoPetal state;
    state.phase=(t-14.0)*0.30;
    state.morph=vec3(smoothstep(16.7+lane*0.10,21.6+lane*0.10,t),
                    smoothstep(21.5,25.7,t),smoothstep(26.7,31.4,t));
    state.transform=rot((lane-2.0)*0.044*sin(state.phase)+0.065*sin(state.phase*0.7));
    state.scale=0.64+lane*0.083;
    state.shift=vec2(0.0,0.08*sin(state.phase+lane*0.45));
    return state;
}
vec2 geoPetalCurve(float u,GeoPetal state) {
    float a=u*TAU-PI*0.5,phase=state.phase;
    float r=2.65*(1.0+state.morph.x*(0.23*cos(6.0*a+phase)+0.045*cos(12.0*a-phase)));
    vec2 rose=vec2(cos(a)*1.72,sin(a))*r;
    vec2 hypo=vec2(1.72*(2.24*cos(a)+0.72*cos(5.0*a+phase)),
                  2.24*sin(a)-0.72*sin(5.0*a+phase));
    float kr=2.30+0.70*cos(3.0*a+phase);
    vec2 torus=vec2(1.70*kr*cos(2.0*a),0.82*kr*sin(2.0*a)+0.72*sin(3.0*a+phase));
    vec2 at=mix(mix(rose,hypo,state.morph.y),torus,state.morph.z)*state.scale;
    return state.transform*at+state.shift;
}
vec2 geoPetalPoint(float u,float lane,float t) {
    return geoPetalCurve(u,geoPetalSetup(lane,t));
}
vec2 geoPetalCurvature(GeoPetal state) {
    // Absolute Fourier-coefficient bounds for the unchanged rose, hypo- and
    // torus curves; rotate the coordinate bounds along with the lane.
    vec2 rose=vec2(1.72,1.0)*2.65*(1.0+15.035*state.morph.x);
    vec2 hypo=vec2(1.72,1.0)*20.24;
    vec2 torus=vec2(31.11,21.486);
    vec2 bound=mix(mix(rose,hypo,state.morph.y),torus,state.morph.z)*(TAU*TAU*state.scale);
    return abs(state.transform[0])*bound.x+abs(state.transform[1])*bound.y;
}
vec3 geoPetals(vec2 p,float t,float aa) {
    float draw=smoothstep(14.1,17.2,t),net=smoothstep(17.4,19.5,t);
    float camera=1.0+0.045*sin((t-14.0)*0.72);
    vec2 q=p/camera;
    vec3 c=geoOrbits(q,t,3.28,0.62,aa/camera);
    for(int lane=0;lane<5;lane++) {
        float k=float(lane),along=0.0;
        GeoPetal state=geoPetalSetup(k,t);
        vec2 curvature=geoPetalCurvature(state);
        vec2 previous=geoPetalCurve(0.0,state);
        float d=min(dot(q-previous,q-previous),geoSearchDistance2(aa/camera));
        for(int block=0;block<28;block++) {
            float ua=min(float(block*4)/112.0,draw),ub=min(float(block*4+4)/112.0,draw);
            if(ub<=ua) break;
            vec2 last=geoPetalCurve(ub,state);
            vec2 padding=curvature*((ub-ua)*(ub-ua)*0.125)+vec2(0.00002);
            if(geoBoxDistance2(q,previous,last,padding)<=d) {
                for(int j=1;j<=4;j++) {
                    float u=min(float(block*4+j)/112.0,draw);
                    vec2 current=j==4?last:geoPetalCurve(u,state);
                    geoTrack(q,previous,current,min(float(block*4+j-1)/112.0,draw),u,d,along);
                    previous=current;
                }
            }
            previous=last;
        }
        c+=geoRibbon(sqrt(d),along,k,t,lane==4?0.019:0.010,lane==4?1.12:0.76,aa/camera);
    }
    for(int j=0;j<24;j++) {
        float u=float(j)/24.0;
        vec2 a=geoPetalPoint(u,0.0,t),b=geoPetalPoint(u,4.0,t);
        vec2 ahead=geoPetalPoint(u+1.0/24.0,4.0,t);
        vec3 hue=geoPalette(u-t*0.037);
        c+=glow(lineDistance(q,a,b),0.005,hue,0.48*net,aa/camera);
        c+=hue*geoTriangle(q,a,b,ahead,aa/camera)*0.043*net;
        if(j<12) c+=glow(lineDistance(q,a,geoPetalPoint(u+0.25,0.0,t)),0.004,hue,0.16*net,aa/camera);
    }
    float spark=fract((t-14.0)*0.095);
    c+=glow(length(q-geoPetalPoint(spark,4.0,t)),0.050,WHITE,0.90,aa/camera);
    return c*geoLife(t,14.0,34.0);
}
// Four inverse Koch similarities, including the continuously changing bend.
vec2 geoKochEdge(vec2 q,float depth) {
    float metric=1.0;
    for(int k=0;k<4;k++) {
        float theta=(PI/3.0)*smoothstep(0.0,1.0,depth-float(k));
        float child=1.0/(2.0+2.0*cos(theta));
        vec2 normal=vec2(cos(theta*0.5),sin(theta*0.5));
        q.x=min(q.x,1.0-q.x); q-=vec2(child,0.0);
        q-=2.0*max(dot(q,normal),0.0)*normal;
        q=(q+vec2(child,0.0))/child; metric*=child;
    }
    return vec2(length(q-vec2(clamp(q.x,0.0,1.0),0.0)),q.y)*metric;
}
float geoSnowflake(vec2 p,float depth) {
    float d=100.0;
    vec2 v0=vec2(0.0,2.88),v1=vec2(2.494153,-1.44),v2=vec2(-2.494153,-1.44);
    for(int side=0;side<3;side++) {
        vec2 a=side==0?v0:(side==1?v1:v2),b=side==0?v1:(side==1?v2:v0);
        vec2 e=b-a; float span=length(e); vec2 tangent=e/span;
        vec2 local=vec2(dot(p-a,tangent),dot(p-a,vec2(-tangent.y,tangent.x)))/span;
        d=min(d,geoKochEdge(local,depth).x*span);
    }
    return d;
}
vec3 geoKoch(vec2 p,float t,float aa) {
    float depth=4.0*smoothstep(35.5,45.0,t);
    depth-=0.42*smoothstep(46.0,48.0,t)*(0.5+0.5*sin((t-47.0)*1.15));
    float push=smoothstep(44.0,46.5,t)*(1.0-smoothstep(48.5,52.0,t));
    float zoom=1.0+0.42*push;
    vec2 q=rot((t-34.0)*0.040+0.035*sin(t*0.7))*(p/vec2(1.62,1.0)/zoom);
    vec3 c=geoOrbits(p,t,3.25,0.45*(1.0-0.5*push),aa);
    float a=atan(q.y,q.x)/TAU;
    for(int lane=0;lane<4;lane++) {
        float k=float(lane),scale=1.0-k*0.13;
        vec2 local=rot(k*(0.12+0.035*sin(t*0.65)))*q/scale;
        float detail=max(0.0,depth-k*0.20);
        float d=geoSnowflake(local,detail)*scale*zoom;
        c+=geoRibbon(d,a+k*0.09,k,t,lane==0?0.016:0.007,lane==0?1.08:0.65,aa);
    }
    // Rotating subdivisions connect corresponding boundary vertices.
    for(int j=0;j<12;j++) {
        float angle=float(j)*TAU/12.0+(t-34.0)*0.035;
        vec2 ray=vec2(cos(angle),sin(angle));
        float active=smoothstep(37.0,41.0,t);
        c+=glow(lineDistance(p,ray*vec2(1.62,1.0)*1.85,ray*vec2(1.62,1.0)*3.15),
                0.004,geoPalette(float(j)/12.0-t*0.037),0.23*active,aa);
    }
    return c*geoLife(t,34.0,54.0);
}
float geoHarmonic(float a,float t) {
    return sin(a)+smoothstep(60.5,62.5,t)*sin(3.0*a)/3.0
        +smoothstep(64.0,66.0,t)*sin(5.0*a)/5.0
        +smoothstep(68.0,70.0,t)*sin(7.0*a)/7.0;
}
struct GeoWave {
    vec3 harmonics;
    float phase;
    float time;
};
GeoWave geoWaveSetup(float t) {
    GeoWave state;
    state.harmonics=vec3(smoothstep(60.5,62.5,t),smoothstep(64.0,66.0,t),smoothstep(68.0,70.0,t));
    state.phase=(t-54.0)*0.95;
    state.time=t;
    return state;
}
vec2 geoWaveCurve(float u,float lane,GeoWave state) {
    float phase=state.phase,a=TAU*u+phase;
    float unroll=smoothstep(56.2+u*0.7,60.6+u*0.7,state.time);
    vec2 circle=vec2(cos(a)*1.55,sin(a))*(2.65-lane*0.21);
    float waveAngle=phase-u*TAU*1.6,n=lane*2.0+1.0;
    float harmonic=sin(waveAngle)+state.harmonics.x*sin(3.0*waveAngle)/3.0
        +state.harmonics.y*sin(5.0*waveAngle)/5.0+state.harmonics.z*sin(7.0*waveAngle)/7.0;
    float y=lane<0.5?-0.35+1.55*harmonic
          :-2.12-lane*0.40+1.35*sin(n*waveAngle)/n;
    vec2 wave=vec2(mix(-1.30,6.40,u),y);
    return mix(circle,wave,unroll);
}
vec2 geoWaveCurvature(float lane,GeoWave state) {
    float radius=2.65-lane*0.21,n=lane*2.0+1.0,freq=TAU*1.6;
    vec2 circle=vec2(1.55,1.0)*radius*(TAU*TAU);
    float waveY=lane<0.5?1.55*(1.0+dot(state.harmonics,vec3(3.0,5.0,7.0))):1.35*n;
    vec2 wave=vec2(0.0,waveY*freq*freq);
    if(state.time<=56.2) return circle;
    if(state.time>=61.3) return wave;
    float amplitude=lane<0.5?0.35+1.55*(1.0+dot(state.harmonics,vec3(1.0/3.0,0.2,1.0/7.0)))
                             :2.12+lane*0.40+1.35/n;
    float speed=lane<0.5?1.55*freq*(1.0+dot(state.harmonics,vec3(1.0))):1.35*freq;
    vec2 delta=vec2(6.40+1.55*radius,amplitude+radius);
    vec2 velocity=vec2(7.70+1.55*radius*TAU,speed+radius*TAU);
    // Product-rule bound for the u-dependent circle-to-wave smoothstep.
    return max(circle,wave)+velocity*(3.0*0.7/4.4)+delta*(6.0*0.7*0.7/(4.4*4.4));
}
vec3 geoWaves(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0);
    float unroll=smoothstep(57.0,61.5,t);
    GeoWave state=geoWaveSetup(t);
    c+=geoOrbits(p,t,3.16,0.34*(1.0-unroll),aa);
    for(int lane=0;lane<4;lane++) {
        float k=float(lane),d=geoSearchDistance2(aa),along=0.0;
        vec2 curvature=geoWaveCurvature(k,state);
        vec2 previous=geoWaveCurve(0.0,k,state);
        for(int block=0;block<28;block++) {
            float ub=float(block*4+4)/112.0;
            vec2 last=geoWaveCurve(ub,k,state);
            vec2 padding=curvature*(2.0/(112.0*112.0))+vec2(0.00002);
            if(geoBoxDistance2(p,previous,last,padding)<=d) {
                for(int j=1;j<=4;j++) {
                    float u=float(block*4+j)/112.0;
                    vec2 current=j==4?last:geoWaveCurve(u,k,state);
                    geoTrack(p,previous,current,u-1.0/112.0,u,d,along);
                    previous=current;
                }
            }
            previous=last;
        }
        c+=geoRibbon(sqrt(d),along,k,t,lane==0?0.018:0.008,lane==0?1.14:0.66,aa);
    }
    float phase=(t-54.0)*0.95;
    vec2 origin=vec2(-4.28,-0.35),endpoint=origin;
    for(int harmonic=0;harmonic<4;harmonic++) {
        float k=float(harmonic),n=k*2.0+1.0;
        float begin=harmonic==1?60.5:(harmonic==2?64.0:68.0);
        float grow=harmonic==0?1.0:smoothstep(begin,begin+2.0,t);
        float radius=1.55*grow/n;
        vec2 next=endpoint+radius*vec2(cos(n*phase),sin(n*phase));
        vec3 hue=geoPalette(k*0.19-t*0.037);
        c+=glow(abs(length(p-endpoint)-radius),0.008,hue,0.72*unroll*grow,aa);
        c+=glow(lineDistance(p,endpoint,next),0.008,hue,0.92*unroll*grow,aa);
        c+=glow(length(p-next),0.029,WHITE,0.75*unroll*grow,aa);
        endpoint=next;
    }
    vec2 head=vec2(-1.30,-0.35+1.55*geoHarmonic(phase,t));
    c+=glow(lineDistance(p,endpoint,head),0.006,GOLD,0.68*unroll,aa);
    c+=glow(length(p-head),0.043,WHITE,unroll,aa);
    c+=glow(lineDistance(p,vec2(-6.6,-0.35),vec2(6.6,-0.35)),0.004,CYAN,0.23*unroll,aa);
    c+=glow(lineDistance(p,vec2(-4.28,-2.55),vec2(-4.28,1.85)),0.004,CYAN,0.20*unroll,aa);
    return c*geoLife(t,54.0,74.0);
}
struct GeoSheet {
    vec3 morph;
    mat2 transform;
    float phase;
};
GeoSheet geoSheetSetup(float t) {
    GeoSheet state;
    state.morph=vec3(smoothstep(75.0,79.2,t),smoothstep(78.5,83.0,t),smoothstep(86.2,92.5,t));
    state.phase=(t-74.0)*0.43;
    state.transform=rot(0.035*sin(state.phase));
    return state;
}
vec2 geoSheetCurve(float u,float v,GeoSheet state) {
    float grow=state.morph.x,fold=state.morph.y,crown=state.morph.z;
    float a=u*TAU,phase=state.phase;
    vec3 sheet=vec3((u*2.0-1.0)*5.65,
                    0.55*sin(a-phase)+v*1.55*grow,
                    (v*0.92*sin(a*2.0+phase)+0.38*sin(a*3.0-phase))*grow*fold);
    vec2 projected=vec2(sheet.x+sheet.z*0.48,sheet.y*0.81+sheet.z*0.74);
    float radius=2.30+0.76*v+0.26*cos(5.0*a-phase);
    vec2 torus=vec2(1.75*radius*cos(a+phase*0.13),
                   0.84*radius*sin(a+phase*0.13)+0.48*v*sin(3.0*a+phase));
    return state.transform*mix(projected,torus,crown)+vec2(0.0,-0.50);
}
vec2 geoSheetCurvature(float v,GeoSheet state) {
    float bend=(3.68*abs(v)+3.42)*state.morph.x*state.morph.y;
    vec2 sheet=vec2(0.48*bend,0.4455+0.74*bend);
    float radius=abs(2.30+0.76*v)+6.76;
    vec2 torus=vec2(1.75*radius,0.84*radius+4.32*abs(v));
    vec2 bound=mix(sheet,torus,state.morph.z)*(TAU*TAU);
    return abs(state.transform[0])*bound.x+abs(state.transform[1])*bound.y;
}
vec3 geoSheets(vec2 p,float t,float aa) {
    vec3 c=vec3(0.0); float grow=smoothstep(75.0,79.2,t);
    GeoSheet state=geoSheetSetup(t);
    for(int j=0;j<32;j++) {
        float u=float(j)/32.0,w=float(j+1)/32.0;
        vec2 a=geoSheetCurve(u,-1.0,state),b=geoSheetCurve(w,-1.0,state);
        vec2 d=geoSheetCurve(u,1.0,state),e=geoSheetCurve(w,1.0,state);
        vec3 hue=geoPalette(u*0.90-t*0.037);
        float face=geoTriangle(p,a,b,d,aa)+geoTriangle(p,b,e,d,aa);
        c+=hue*face*0.048*grow;
        c+=glow(lineDistance(p,a,d),0.006,hue,0.66*grow,aa);
        c+=glow(lineDistance(p,a,e),0.004,geoPalette(u+0.25-t*0.037),0.30*grow,aa);
    }
    for(int lane=0;lane<9;lane++) {
        float k=float(lane),v=k*0.25-1.0,d=geoSearchDistance2(aa),along=0.0;
        vec2 curvature=geoSheetCurvature(v,state);
        vec2 previous=geoSheetCurve(0.0,v,state);
        for(int block=0;block<16;block++) {
            float ub=float(block*4+4)/64.0;
            vec2 last=geoSheetCurve(ub,v,state);
            vec2 padding=curvature*(1.0/2048.0)+vec2(0.00002);
            if(geoBoxDistance2(p,previous,last,padding)<=d) {
                for(int j=1;j<=4;j++) {
                    float u=float(block*4+j)/64.0;
                    vec2 current=j==4?last:geoSheetCurve(u,v,state);
                    geoTrack(p,previous,current,u-1.0/64.0,u,d,along);
                    previous=current;
                }
            }
            previous=last;
        }
        bool edge=lane==0||lane==8;
        c+=geoRibbon(sqrt(d),along,k*0.65,t,edge?0.017:0.007,edge?1.04:0.68,aa)*(lane==4?1.0:grow);
    }
    float cursor=fract((t-74.0)*0.080);
    c+=glow(length(p-geoSheetCurve(cursor,1.0,state)),0.043,WHITE,0.90,aa);
    c+=geoOrbits(p-vec2(0.0,-0.50),t,3.30,0.26*smoothstep(87.0,92.0,t),aa);
    return c*geoLife(t,74.0,96.0);
}
float geoHexagon(vec2 p) {
    p=abs(p);
    return max(p.y,max(p.x*0.8660254+p.y*0.5,p.x*0.8660254-p.y*0.5))-0.8660254;
}
vec3 geoStar(vec2 p,float t,float aa) {
    float local=t-96.0,assembly=smoothstep(96.0,99.0,t);
    float depth=1.0+3.0*smoothstep(98.5,106.5,t);
    float camera=1.0+0.06*sin(local*0.75);
    vec2 q=rot(local*0.14+0.045*sin(local))*vec2(p.x/1.70,p.y)/(3.06*camera);
    float scale=3.06*camera,valid=1.0;
    vec3 c=geoOrbits(p,t,3.34,0.82,aa);
    // Seven similarities at every level; each branch turns within its parent.
    // Nearest-child folding evaluates 7^4 pieces with only 4 x 6 candidates.
    for(int level=0;level<4;level++) {
        float k=float(level),spread=level==0?mix(1.02,2.0/3.0,assembly):2.0/3.0;
        vec2 chosen=vec2(0.0); float nearest=geoHexagon(q*3.0)/3.0,branch=0.0;
        for(int child=0;child<6;child++) {
            float a=float(child)*PI/3.0;
            vec2 center=vec2(cos(a),sin(a))*spread;
            float candidate=geoHexagon((q-center)*3.0)/3.0;
            if(candidate<nearest) { nearest=candidate; chosen=center; branch=float(child+1); }
        }
        float reveal=smoothstep(k+0.02,k+0.78,depth),sd=nearest*scale;
        float ink=1.0-smoothstep(-aa,aa,sd);
        vec3 hue=geoPalette(k*0.17+branch*0.073-local*0.057+atan(q.y,q.x)/TAU*0.24);
        c+=hue*ink*(0.038-0.005*k)*valid*reveal;
        c+=glow(abs(sd),level==0?0.014:0.006,hue,(level==0?0.96:0.78)*valid*reveal,aa);
        valid*=ink;
        q=rot(0.07*sin(local*0.8+k*1.2))*(q-chosen)*3.0;
        scale/=3.0;
    }
    vec2 polar=p/vec2(1.70,1.0); float r=length(polar),a=atan(polar.y,polar.x)-local*0.14;
    for(int ring=0;ring<3;ring++) {
        float k=float(ring);
        float radius=2.85+k*0.16+0.17*cos(6.0*a+local*0.6+k*0.7);
        c+=glow(abs(r-radius),0.006,geoPalette(a/TAU+k*0.17-local*0.045),0.62*assembly,aa);
    }
    float spoke=abs(sin(a*6.0))*r/6.0;
    float band=smoothstep(2.7,2.8,r)*(1.0-smoothstep(3.35,3.55,r));
    c+=glow(spoke,0.005,GOLD,0.36*assembly,aa)*band;
    return c*geoLife(t,96.0,112.0);
}
vec2 geoClosingCurve(float u,float lane,float t,float settle) {
    float y=-1.78+(lane-2.0)*0.06+sin(PI*u)*(1.0-settle)*0.52*sin(u*TAU+lane*0.35-t*0.4);
    return vec2(mix(-5.9,5.9,u),y);
}
vec3 geoClosing(vec2 p,float t,float aa) {
    float settle=smoothstep(112.0,116.4,t);
    vec3 c=geoOrbits(p,t,3.12,0.49*(1.0-0.36*settle),aa);
    for(int lane=0;lane<5;lane++) {
        float k=float(lane),d=geoSearchDistance2(aa),along=0.0;
        vec2 previous=vec2(-5.9,-1.78+(k-2.0)*0.06);
        vec2 padding=vec2(0.00002,(1.0-settle)*0.52*9.0*PI*PI/512.0+0.00002);
        for(int block=0;block<8;block++) {
            vec2 last=geoClosingCurve(float(block*8+8)/64.0,k,t,settle);
            if(geoBoxDistance2(p,previous,last,padding)<=d) {
                for(int j=1;j<=8;j++) {
                    float u=float(block*8+j)/64.0;
                    vec2 current=j==8?last:geoClosingCurve(u,k,t,settle);
                    geoTrack(p,previous,current,u-1.0/64.0,u,d,along);
                    previous=current;
                }
            }
            previous=last;
        }
        c+=geoRibbon(sqrt(d),along,k,t,lane==2?0.013:0.006,lane==2?0.80:0.42,aa);
    }
    return c*smoothstep(112.0,112.8,t);
}
vec3 geometryAct(vec2 p,float t,float aa) {
    if(abs(p.x)>7.8 || abs(p.y)>4.3) return vec3(0.0);
    if(t<14.0) return geoOpening(p,t,aa);
    if(t<34.0) return geoPetals(p,t,aa);
    if(t<54.0) return geoKoch(p,t,aa);
    if(t<74.0) return geoWaves(p,t,aa);
    if(t<96.0) return geoSheets(p,t,aa);
    if(t<112.0) return geoStar(p,t,aa);
    return geoClosing(p,t,aa);
}
