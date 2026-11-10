// Closed contour correspondence, stored in the existing atlas' lower half.
// All loops are fixed-budget; each glyph rejects its screen box before reads.
mat2 vmRot(float angle) {
    return mat2(cos(angle),-sin(angle),sin(angle),cos(angle));
}
void vmPaint(inout vec3 c,vec3 hue,float coverage) {
    // __VECTOR_COMPOSITE__
}
float vmSdfCoverage(vec2 q,vec4 tile) {
    float distance=sdfSample(q,tile);
    float edge=clamp(0.5*fwidth(distance),0.55,12.0);
    return smoothstep(-edge,edge,distance);
}
void vectorStaticGlyph(inout vec3 c,vec2 p,vec2 a,vec2 sa,vec4 ta,
                       vec2 b,vec2 sb,vec4 tb,float u,float arc,
                       vec3 hue,float opacity,float aa) {
    float lift=sin(3.14159265359*u);
    vec2 center=mix(a,b,u)+vec2(arc*0.21,arc)*lift;
    vec2 size=max(mix(sa,sb,u),vec2(0.00001));
    vec2 local=vmRot(lift*arc*0.16)*(p-center);
    vec2 q=local/size+0.5;
    if(min(q.x,q.y)<0.005 || max(q.x,q.y)>0.995 || opacity<0.001) return;
    vmPaint(c,hue,opacity*vmSdfCoverage(q,ta));
}
vec2 vmReadPoint(float index) {
    vec2 pixel=vec2(mod(index,4096.0),floor(index/4096.0));
    vec4 bytes=floor(texture2D(TEXTURE_2,(pixel+0.5)/4096.0)*255.0+0.5);
    return vec2(bytes.r*256.0+bytes.g,bytes.b*256.0+bytes.a)/65535.0;
}
void vectorGlyph(inout vec3 c,vec2 p,vec2 a,vec2 sa,vec4 ta,
                 vec2 b,vec2 sb,vec4 tb,float u,float arc,
                 vec3 hue,float opacity,float aa,vec2 data,vec2 present) {
    if(opacity<0.001) return;
    if(u<=0.0) {
        if(present.x>0.5) vectorStaticGlyph(c,p,a,sa,ta,a,sa,ta,0.0,0.0,hue,opacity,aa);
        return;
    }
    if(u>=1.0) {
        if(present.y>0.5) vectorStaticGlyph(c,p,b,sb,tb,b,sb,tb,0.0,0.0,hue,opacity,aa);
        return;
    }
    float lift=sin(3.14159265359*u);
    vec2 center=mix(a,b,u)+vec2(arc*0.21,arc)*lift;
    vec2 size=max(mix(sa,sb,u),vec2(0.00001));
    vec2 local=vmRot(lift*arc*0.16)*(p-center);
    vec2 q=local/size+0.5;
    if(min(q.x,q.y)<0.005 || max(q.x,q.y)>0.995) return;
    float distanceSquared=1e8;
    float winding=0.0;
    float fanArea=0.0;
    float coverage=0.0;
    float componentOuter=0.0;
    float componentHoles=0.0;
    float edge=max(aa*0.55,0.00001);
    vec2 previous=vec2(0.0);
    vec2 origin=vec2(0.0);
    bool connected=false;
    for(int i=0;i<256;i++) {
        if(float(i)>=data.y) break;
        float address=data.x+float(i)*2.0;
        vec2 first=vmReadPoint(address);
        vec2 second=vmReadPoint(address+1.0);
        if(first.x>0.99999 && first.y>0.99999) {
            float signedDistance=sqrt(distanceSquared)*(abs(winding)>0.5?1.0:-1.0);
            // Zero-area paths have no ink, including their AA footprint.
            // Absolute triangle fan area also handles self-intersecting loops
            // whose signed lobes would otherwise cancel and flash off.
            float loopCoverage=smoothstep(-edge,edge,signedDistance)
                *smoothstep(0.0,edge*edge,fanArea);
            if(second.x<0.5) {
                coverage=max(coverage,componentOuter*(1.0-componentHoles));
                componentOuter=loopCoverage;
                componentHoles=0.0;
            } else {
                componentHoles=max(componentHoles,loopCoverage);
            }
            distanceSquared=1e8;
            winding=0.0;
            fanArea=0.0;
            connected=false;
            continue;
        }
        vec2 current=(mix(first,second,u)-0.5)*size;
        if(connected) {
            vec2 segment=current-previous;
            vec2 relative=local-previous;
            float lengthSquared=dot(segment,segment);
            if(lengthSquared>1e-16) {
                float along=clamp(dot(relative,segment)/lengthSquared,0.0,1.0);
                vec2 delta=relative-along*segment;
                distanceSquared=min(distanceSquared,dot(delta,delta));
                float side=segment.x*relative.y-segment.y*relative.x;
                if(previous.y<=local.y && current.y>local.y && side>0.0) winding+=1.0;
                if(previous.y>local.y && current.y<=local.y && side<0.0) winding-=1.0;
                vec2 firstArm=previous-origin;
                vec2 secondArm=current-origin;
                fanArea+=0.5*abs(firstArm.x*secondArm.y-firstArm.y*secondArm.x);
            }
        } else {
            origin=current;
        }
        previous=current;
        connected=true;
    }
    coverage=max(coverage,componentOuter*(1.0-componentHoles));
    // Only endpoint AA is reconciled; unrelated glyph distance fields never mix.
    if(u<0.025 && present.x>0.5)
        coverage=mix(vmSdfCoverage(q,ta),coverage,smoothstep(0.0,0.025,u));
    if(u>0.975 && present.y>0.5)
        coverage=mix(coverage,vmSdfCoverage(q,tb),smoothstep(0.975,1.0,u));
    vmPaint(c,hue,coverage*opacity);
}
